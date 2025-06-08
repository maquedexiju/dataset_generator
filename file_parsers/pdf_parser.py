import fitz
import json
import os
import re
import base64
import io
from openai import OpenAI
from PIL import Image
from transformers.models.align.modeling_align import correct_pad
import uuid

from .basic_parser import BasicParser

# bbox 识别还是有一堆问题，像素不准确，格式不准确
doc_pdf_parse_prompt = '''
你是一个图像识别助手，识别图片中文档的排版及内容，内容必须是完整、准确的，不能缺失任何内容，不能包含错误或编造的内容。

## 前一段内容

{former_content}

## 识别文档的内容块

针对每个内容块，识别以下信息：

1. type 包括：标题、正文、列表、脚注、图表、表格、公式块、代码块、页眉、页脚、其他，判定逻辑同时参考以下规则：
    1. 根据内容所处位置是否在正文边距外，且无实质意义，判定是否为页眉或页脚
    2. 标题：通过字体是否比其他内容大，来判断内容是否为标题，页眉、页脚中的标题判定为页眉、页脚
2. content
    1. 采用 md 格式，换行使用 \\n，对 latex 公式中的反斜杠使用 \\ 转义
    2. 针对 type 为标题的
    3. 针对 type 为正文、列表的，识别行内公式、行内代码、加粗、斜体、高亮等标记
    4. 针对 type 为表格的
        1. 识别是否包含表头
            1. 如果包含表头，正常返回 md 格式表格
            2. 如果不包含表头，则返回内容增加不包含表头的内容
        2. 出现跨行或跨列的单元格，使用 “@cross_row_n” 或 “@cross_col_n” 标记，其中 n 为跨的行数或列数
        3. 单元格中的换行使用 <br/>
    5. 针对 type 为代码块的，尝试识别代码语言，使用 ‍``` 包裹
    6. 针对 type 为公式块的，识别公式，使用 $$ 包裹
    7. 针对 type 为标注的，根据标记编号，识别对应正文内容中的位置及对应的 note_id，使用 “[^note_id]: ” 开头；对于未找到对应 note_id 的标注，使用 “[^not_found]: ” 开头
    8. 针对 type 为图表的
        1. content 格式为：\\n@resource: block_id \\n\\n图表简述：\\n图表的详细描述\\n@endresource\\n
        2. 其中图表简述为图表的简要描述，尽量不超过 20 个字
        3. 其中图表的详细描述如果较长，可采用列表的方式
3. bbox 是一个列表，包含四个元素，分别是左上角和右下角的 x 和 y 坐标，坐标值为三位小数，代表相对于图片的比例
4. continued 是一个布尔值，针对正文、表格或代码块，判断当前内容是否是上方给出“前一段内容”的延续，如果“前一段内容”为空，则为 false

同时为 block 生成 block_id，block_id 从 1 开始依次编号

## 处理脚注编号

根据 type 为脚注的块，对内容块信息进行更新

1. 识别脚注编号，并在标题、正文、列表、表格和公式块中查找对应编号
2. 取 uuid 的前 8 位，生成唯一编号 note_id
3. 将标题、正文、列表、表格和公式块中的编号改为 “[^{note_id}]”
4. 将脚注中的编号删除，并改为 “[^{note_id}]: ” 开头

## 返回格式

请严格按照下列格式返回

{
    "blocks": [
        {
            "id" : block_id,
            "type": "类型",
            "content": "内容",
            "bbox": [x1, y1, x2, y2],
            "continued": "是否为 continued block，true 或 false",
        }
    ]
}

举例：

{
    "blocks": [
        {
            "id" : 1,
            "type": "页眉",
            "content": "原则",
            "bbox": [0.823, 0.115, 0.982, 0.173],
            "continued": false
        },
        {
            "id": 2,
            "type": "正文",
            "content": "我们的首要原则是发现并处理核心问题[^345c5840]",
            "bbox": [0.112, 0.223, 0.982, 0.305],
            "continued": false
        },
        {
            "id": 3,
            "type": "代码块",
            "content": "```python\\ndef hello_world():\\n    print(\"Hello, World!\")\\n```",
            "bbox": [0.112, 0.323, 0.982, 0.505],
            "continued": false
        },
        {
            "id": 4,
            "type": "表格",
            "content": "| 序号 | 名称 | 描述 |\\n| ---- | ---- | ---- |\\n| 1 | 核心问题 | 与生存相关的问题 |\\n| 2 | 非核心问题 | 与生存无关的问题 |",
            "bbox": [0.112, 0.523, 0.982, 0.705],
            "continued": false
        },
        {
            "id": 5,
            "type": "公式块",
            "content": "$$\\\\int_0^\\\\infty x^2 dx = \\\\frac{x^3}{3} |_0^\\\\infty = \\\\infty$$",
            "bbox": [0.112, 0.723, 0.532, 0.805],
            "continued": false
        },
        {
            "id": 6,
            "type": "图表",
            "content": "\\n@resource: 6 \\n\\n图表简述：这是一个图表的简要描述\\n图表的详细描述：这是一个图表的详细描述\\n@endresource\\n",
            "bbox": [0.112, 0.810, 0.982, 0.912],
            "continued": false
        },
        {
            "id": 4,
            "type": "脚注",
            "content": "[^345c5840]: 核心问题指的是与生存相关的问题",
            "bbox": [0.564, 0.913, 0.982, 0.985],
            "continued": false
        }
    ]
}
'''

img_pdf_parse_prompt = '''
你是一个图像识别助手，识别图片中的文档的排版及内容，采用 md 格式返回文档内容，注意：
'''

ppt_parse_prompt = '''
你是一个图像识别助手，识别图片中的 PPt 内容，包括页面类型、标题、内容、图表等，并返回 json。
页面类型包括：标题、目录、内容、其他。
返回的 json 格式如下：
{
    "page_type": "页面类型", # 必选
    "title": "页面标题", # 可选
    "summary": "页面内容一句话总结", # 必选
    "content": "内容的详细解析", # 可选
    "chart": {"图表标题": "图表概述"}, # 可选
    "table": {"表格标题"：“表格内容”} # 可选
}
注意：
1. 内容必须是完整、准确的，不能缺失任何内容，不能包含错误或编造的内容。
2. table 和 content 采用 md 格式，换行使用 \\n，单元格中的换行使用 <br/>
3. 图表标题、表格标题尽量以 PPt 中的内容为准，也可以根据内容自行总结。
4. 请严格按照上述格式返回
'''

determine_heading_level_prompt = '''
你是一个文档标题识别助手，参考文档目录名称，识别并调整标题的级别

## 文档目录名称

{toc_list}

## 需要调整的标题

{heading_list}

## 调整规则

1. 对于连续重复的标题，保留第一个，并设置其他重复标题的级别为 0
2. 优先参考文档目录名称，调整标题的级别，级别从 1 开始，1 表示一级标题，2 表示二级标题，以此类推
3. 如果文档目录名称为空，则按照标题的内容进行调整
4. 不要调整标题的内容、id和列表的顺序

## 返回格式

[
    {
        "content": "标题",
        "level": 调整后的级别，int 类型,
        "id": 标题的 id
    }
]
'''

class PDFParser(BasicParser):
    suffix = 'pdf'
    def __init__(self, file_path, root_path, cfg={}, title_prefix='%parent', logger=None):
        # 检查文件类型
        if not file_path.lower().endswith('.pdf'):
            raise ValueError("file type error, not a pdf file")

        # 获取图像识别模型的相关算法配置
        self.img_parse_url = cfg['IMG_RECONGNIZE_MODEL']['url']
        self.img_parse_key = cfg['IMG_RECONGNIZE_MODEL']['api_key']
        self.img_parse_model = cfg['IMG_RECONGNIZE_MODEL']['model_name']
        self.openai_client = OpenAI(api_key=self.img_parse_key, base_url=self.img_parse_url)

        # 获取他llm 相关算法配置
        self.llm_url = cfg['LLM']['url']
        self.llm_key = cfg['LLM']['api_key']
        self.llm_model = cfg['LLM']['model_name']
        self.llm_client = OpenAI(api_key=self.llm_key, base_url=self.llm_url)

        super().__init__(file_path, root_path, cfg, title_prefix, logger)

        self.pdf_doc = fitz.open(self.file_path)
        self.toc = self.pdf_doc.get_toc()

        # 获取 page_sizes
        self.page_sizes = {}
        for page in self.pdf_doc:
            r = page.rect
            if r not in self.page_sizes.keys():
                self.page_sizes[r] = 0
            self.page_sizes[r] += 1
        
        # # 创建 chart_output_dir
        # self.chart_output_dir = os.path.join(self.output_dir, 'chart')
        # if not os.path.exists(self.chart_output_dir):
        #     os.makedirs(self.chart_output_dir)

        # # 创建 table_output_dir
        # self.table_output_dir = os.path.join(self.output_dir, 'table')
        # if not os.path.exists(self.table_output_dir):
        #     os.makedirs(self.table_output_dir)

        # 创建 img_output_dir
        self.img_output_dir = os.path.join(self.output_dir, 'img')
        if not os.path.exists(self.img_output_dir):
            os.makedirs(self.img_output_dir)

    
    def __bbox_dict_to_list(self, bbox_dict):
        return [int(bbox_dict['x1']), int(bbox_dict['y1']), int(bbox_dict['x2']), int(bbox_dict['y2'])]

    def _corrent_bbox(self, result_dict, img_pil):

        width, height = img_pil.size

        for blk in result_dict['blocks']:
            x1 = round(blk['bbox'][0] * width)
            y1 = round(blk['bbox'][1] * height)
            x2 = round(blk['bbox'][2] * width)
            y2 = round(blk['bbox'][3] * height)

            blk['bbox'] = [x1, y1, x2, y2]

        return result_dict

    
    def _get_md_headings(self):
        # 遍历 md_content，获取所有的 heading
        headings = []
        is_in_code = False
        for l in self.md_content.split('\n'):
            if l.startswith('```'):
                is_in_code = not is_in_code
                continue
            if is_in_code:
                continue
            if l.startswith('# '):
                # 获取 heading 的级别
                level = len(l.split(' ')[0])
                # 获取 heading 的内容
                content_with_id = ' '.join(l.split(' ')[1:])
                content = content_with_id.split('@=@')[0]
                heading_id = content_with_id.split('@=@')[1]
                headings.append({'content': content, 'level': level, 'id': heading_id})

        return headings

    
    def _correct_heading_level(self, headings):
        # 遍历 headings，获取所有的 heading
        doc_toc = []
        for level, content, _ in self.toc:
            doc_toc.append({'content': content, 'level': level})
        
        # prompt = determine_heading_level_prompt.format(
        #     toc_list=json.dumps(doc_toc, ensure_ascii=False, indent=4),
        #     heading_list=json.dumps(headings, ensure_ascii=False, indent=4)
        # )
        prompt = determine_heading_level_prompt.replace('{toc_list}', json.dumps(doc_toc, ensure_ascii=False, indent=4))
        prompt = prompt.replace('{heading_list}', json.dumps(headings, ensure_ascii=False, indent=4))

        # 调用 OpenAI 的 API 进行图像识别
        try:
            response = self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {"role": "system", "content": prompt}
                ]
            )
        except Exception as e:
            self.logger.error(f'调用 OpenAI API 失败，错误信息：{e}')
        
        result_str = response.choices[0].message.content
        # with open('PDFParser_correct_heading_level_response.json', 'r') as f:
        #     result_str = f.read()
        if self.cfg['LOG']['log_level'] in ['DEBUG', 'INFO']:
            with open('PDFParser_correct_heading_level_response.json', 'w', encoding='utf-8') as f:
                    f.write(result_str)
        try:
            result = json.loads(result_str)
        except json.JSONDecodeError:
            self.logger.warning(f'解析 OpenAI API 返回的 JSON 失败：{result_str}')
        
        return result

    
    def _replace_heading(self, headings):
        # 遍历 headings，获取所有的 heading
        for heading in headings:
            # 替换 md_content 中的 heading
            # reg = re.compile('#+ ' + heading['content'] + '@=@' + heading['id'] + '[\s\n]+')
            reg = r'#+ ' + heading['content'] + '@=@' + heading['id'] + r'[\s\n]+'
            if heading['level'] == 0:
                corret_heading = ''
            else:
                corret_heading = '#'*heading['level']+' '+heading['content'] + '\n\n'

            # self.md_content = self.md_content.replace(reg, corret_heading)
            self.md_content = re.sub(reg, corret_heading, self.md_content)

    
    def _correct_latex_formula(self, content):

        # 识别 $$ 开头和结尾的公式
        # reg_block = re.compile(r'\$\$([\s\S]+?)\$\$')
        # 识别 $$ 开头和结尾的公式
        reg_line = re.compile(r'\$+[^$]+\$+') # 匹配 $$ 和 $ 包裹的内容

        for match in re.findall(reg_line, content):
            # 把所有 \\ 先变成 \
            modified_formula = match.replace('\\\\', '\\')
            # 把所有 \ 变成 \\（包括上一步转换的，和之前就只有 1 个杠的）
            modified_formula = modified_formula.replace('\\', '\\\\')
            content = content.replace(match, modified_formula)

        return content

    def judge_pdf_type(self):

        # 根据文档是否有文字判断是否是纯图片
        text = ''.join([x.get_text() for x in self.pdf_doc])
        if text == '': img = True
        else: img = False

        # 如果 pdf 中有目录，那么是文档
        if self.toc != []:
            self.doc_content = []
            return 'doc', img

        # 根据 pdf 的页面宽高判断类型（主要是考虑页面布局识别的难度）
        ## 取最多的 page_size
        page_size = max(self.page_sizes, key=self.page_sizes.get)
        ## 获取宽高比
        ratio = page_size.width / page_size.height
        ## 如果宽高比小于 0.8，那么是文档
        if ratio < 0.8:
            self.doc_content = []
            return 'doc', img
        ## 如果宽高比大于 1.3，那么是 ppt
        if ratio > 1.3:
            return 'ppt', img
        else:
            return 'unknown', img


    def parse_doc_page(self, pg_pil_img, page_number, former_content=''):
        # 调用 OpenAI 的 API 进行图像识别
        
        # 确保 pg_pil_img 是 RBG 模式
        if pg_pil_img.mode != 'RGB':
            pg_pil_img = pg_pil_img.convert('RGB')
        
        # 将 PIL 图像转换为 base64 编码
        byte_arr = io.BytesIO()
        pg_pil_img.save(byte_arr, format='JPEG')
        b64_img = base64.b64encode(byte_arr.getvalue()).decode('utf8')

        # 发起请求
        prompt = doc_pdf_parse_prompt.replace( '{former_content}', former_content)
        # try:
        #     response = self.openai_client.chat.completions.create(
        #         model=self.img_parse_model,
        #         messages=[
        #             {"role": "system", "content": prompt},
        #             {"role": "user", "content": [
        #                 {
        #                     "type": "image_url",
        #                     "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}
        #                 }
        #             ]}
        #         ]
        #     )
        # except Exception as e:
        #     self.logger.error(f'调用 OpenAI API 失败，错误信息：{e}')
        #     raise ValueError(f'调用 OpenAI API 失败，错误信息：{e}')

        # result_str = response.choices[0].message.content
        with open(f'PDFParser_parse_doc_page_response_{page_number}.json', 'r', encoding='utf-8') as f:
            result_str = f.read()
        result_str = self._correct_latex_formula(result_str)

        if self.cfg['LOG']['log_level'] in ['DEBUG', 'INFO']:
            with open(f'PDFParser_parse_doc_page_response_{page_number}.json', 'w', encoding='utf-8') as f:
                    f.write(result_str)


        try:
            result = json.loads(result_str)
        except json.JSONDecodeError:
            self.logger.warning(f'解析 OpenAI API 返回的 JSON 失败：{result_str}')
            raise ValueError(f'解析 OpenAI API 返回的 JSON 失败：{result_str}')

        # 把百分比的 bbox 转换为像素值
        result = self._corrent_bbox(result, pg_pil_img)

        self.doc_content.append(result)

        last_useful_block = [x for x in result['blocks'] if x['type'] not in ['页眉', '页脚', '脚注']][-1]
        return last_useful_block['content']

        
        # 处理图表
        for blk in [x for x in result['blocks'] if x['type'] == '图表']:
            # 根据 bbox 获取图片
            img = pg_pil_img.crop(blk['bbox'])
            img_path = os.path.join(self.chart_output_dir, f'page_{page_number}_chart_{blk["id"]}.jpg')
            img.save(img_path)

            # 替换 result 中的图片信息
            former_info = f'@resource: {blk["id"]}'
            img_name = f'page_{page_number}_chart_{blk["id"]}.jpg'
            new_info = f'@resource: {self.knowledge_path}: {img_name}'
            result['full_text'] = result['full_text'].replace(former_info, new_info)
        
        # 处理表格
        for blk in [x for x in result['blocks'] if x['type'] == '表格']:
            print('@@@@@@')
            print(blk['bbox'])
            print(pg_pil_img.size)
            # 根据 bbox 获取图片
            img = pg_pil_img.crop(blk['bbox'])
            img_path = os.path.join(self.table_output_dir, f'page_{page_number}_table_{blk["id"]}.jpg')
            img.save(img_path)

        # # 处理页面，保存下来
        # img_list = [x for x in result['blocks'] if x['type'] == '图表']
        # if img_list != []:
        #     img_name = f'page_{page_number}.jpg'
        #     img_path = os.path.join(self.img_output_dir, img_name)
        #     pg_pil_img.save(img_path)

        #     for blk in img_list:
        #         former_info = f'@resource: {blk["id"]}'
        #         new_info = f'@resource: {self.knowledge_path}: {img_name}'
        #         result['full_text'] = result['full_text'].replace(former_info, new_info)
            

    
    def assemble_doc_md(self):
        # 对 doc_content 进行处理，返回完整的 md 内容
        # 标题先统一处理成一级标题，并添加唯一标识，后面再处理
        full_msg = {}
        full_text = ''
        notes = []
        former_block = {
            'type': 'not_found',
            'content': ''
        }
        for page_number in range(len(self.doc_content)):
            full_msg[page_number+1] = self.doc_content[page_number]['blocks']

            notes_for_one_page = []
            for b in self.doc_content[page_number]['blocks']:
                
                # 标题、正文、列表、脚注、图表、表格、公式块、代码块、页眉、页脚、其他
                if b['type'] == '页眉' or b['type'] == '页脚':
                    continue
                elif b['type'] == '脚注':
                    notes_for_one_page.append(b['content'])
                elif b['type'] == '标题': # 统一先变成一级标题，后面再处理
                    # 生成一个唯一的 id
                    heading_id = str(uuid.uuid4())[:8]
                    content = '# ' + b['content'] + f'@=@{heading_id}' + '\n'
                    full_text += content + '\n'
                elif b['continued'] == True:
                    # 处理代码
                    if b['type'] == '代码块' and former_block['type'] == '代码块' and full_text.endswith('```\n'):
                        content_list = b['content'].split('\n')[1:]
                        content = '\n'.join(content_list)
                        full_text = full_text[:-4] + '\n' + content + '\n'
                    elif b['type'] == '表格' and former_block['type'] == '表格' and full_text.endswith('|\n'):
                        full_text += b['content'] + '\n'
                    elif b['type'] == '正文' and former_block['type'] == '正文':
                        full_text = full_text[:-1] + b['content'] + '\n'
                    # 不满足有效条件的，类型不对，或者 former_block 类型不对
                    else:
                        full_text += b['content'] + '\n'
                        self.logger.warning(f'页面 {page_number+1} 中 block {b["id"]} 类型为 {b["type"]} 是延续块，但前一个有效内容 {former_block} 不匹配，full_text 末尾为：{full_text[-20:]}')

                else:
                    full_text += b['content'] + '\n'
                
                # 设置为前一个 block
                if b['type'] not in ['页眉', '页脚', '脚注']:
                    former_block = b

            # 处理脚注
            for nt in notes_for_one_page:
                note_id = nt.split(': ')[0]
                note_content = ': '.join(nt.split(': ')[1:])
                if note_id in full_text:
                    full_text = full_text.replace(note_id, f'(注：{note_content})')
                else:
                    self.logger.warning(f'页面 {n+1} 中未找到 {note_id}，注释内容为：{note_content}')
            notes += notes_for_one_page

        
        # full_msg 导出到 output_dir
        with open(os.path.join(self.output_dir, 'full_msg.json'), 'w', encoding='utf-8') as f:
            json.dump(full_msg, f, ensure_ascii=False, indent=4)

        # notes 导出到 output_dir
        with open(os.path.join(self.output_dir, 'notes.txt'), 'w', encoding='utf-8') as f:
            for nt in notes:
                f.write(nt + '\n')
        
        # full_text 导出到 output_dir
        with open(os.path.join(self.output_dir, 'full_text.md'), 'w', encoding='utf-8') as f:
            f.write(full_text)

        self.md_content = full_text


    def split_doc_md(self):

        # 处理标题
        headings = self._get_md_headings()
        corrected_headings = self._correct_heading_level(headings)
        self._replace_heading(corrected_headings)
        with open(os.path.join(self.output_dir, 'full_text.md'), 'w', encoding='utf-8') as f:
            f.write(self.md_content)
        

        # 若 md 开头不是一级标题，添加一级标题为文件名
        if not self.md_content.lstrip().startswith('# '):
            self.md_content = f'# {self.file_basename}\n{self.md_content}'

        # 如果 md 中含有多个一级标题，那么 self.title_prefix 保留文件名
        if self.md_content.count('\n# ') > 1:
            if self.file_basename not in self.title_prefix:
                self.title_prefix += '-' + self.file_basename

        result = {}
        headers = []
        current_header_path = ''
        current_content = []

        # 按行遍历 Markdown 内容
        is_in_code = False
        for line in self.md_content.splitlines():

            # 处理代码
            if line.startswith('```'):
                is_in_code = not is_in_code
                continue
            if is_in_code:
                current_content.append(line)
                continue

            # 处理标题
            if line.startswith('#') and not is_in_code:

                # 处理当前标题内容
                if current_header_path and current_content and ''.join(current_content) != '':
                    position = "-".join(headers)
                    result[current_header_path] = self.add_section_tag('\n'.join(current_content).strip(), position)
                    current_content = []

                # 解析新标题级别和文本
                level = line.count('#')
                header_text = line.strip('#').strip()

                # 标题级别错误处理
                if level > len(headers) + 1:
                    self.logger.warning(f'标题级别跳跃: 当前标题级别 {level}, 上一级标题级别 {len(headers)}。标题: {header_text}')
                    # 尝试修正标题级别，设置为上一级标题级别加 1
                    level = len(headers) + 1

                # 调整标题层级
                if level > len(headers):
                    headers.append(header_text)
                elif level == len(headers):
                    headers[-1] = header_text
                else:
                    headers = headers[:level - 1]
                    headers.append(header_text)

                current_header_path = '-'.join([self.title_prefix] + headers)
            else:
                current_content.append(line)

        # 处理最后一个标题内容
        if current_header_path and current_content:
            position = "-".join(headers)
            result[current_header_path] = self.add_section_tag('\n'.join(current_content).strip(), position)

        self.content_dict = result


    def parse(self):
        # 实现具体的解析逻辑
        pdf_type, is_img = self.judge_pdf_type()
        if pdf_type == 'doc':
            former_content = ''
            for pg in self.pdf_doc:
                if pg.number > 2: break
                img_pil = pg.get_pixmap(matrix=fitz.Matrix(2, 2)).pil_image()
                retried = 0
                former_content = self.parse_doc_page(img_pil, pg.number+1, former_content)
                while False:
                    try:
                        former_content = self.parse_doc_page(img_pil, pg.number+1, former_content)
                        self.logger.debug(f'{pg.number+1} 已分析')
                        break
                    except Exception as e:
                        retried += 1
                        if retried > 3:
                            self.logger.error(f'{pg.number+1} 已重试 3 次，跳过该页面')
                            break

                        self.logger.warning(f'页面 {pg.number+1} 分析失败，正在第 {retried} 次重试...')

                self.logger.info(f'{pg.number+1} 已分析')
            
            self.assemble_doc_md()
            self.split_doc_md()

            for k, v in self.content_dict.items():
                self.qa_info.append({
                    'simple_title': k.split(': ')[-1],
                    'full_title': k,
                    'content': v,
                })
            
            return self.qa_info
