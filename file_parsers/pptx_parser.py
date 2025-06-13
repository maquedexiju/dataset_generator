import base64
import os, sys, re
import tempfile
import json
from PIL import Image
import requests
import fitz
from openai import OpenAI

from .basic_parser import BasicParser

if sys.platform.startswith('win'):
    import comtypes.client

ppt_parse_prompt_v1 = '''
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
2. table 和 content 采用 md 格式。
3. 图表标题、表格标题尽量以 PPt 中的内容为准，也可以根据内容自行总结。
'''

ppt_parse_prompt = '''
你是一个图像识别助手，识别图片中的 PPt 内容，包括页面类型、标题、内容、图表等，返回格式如下：

@=@page_type # 必选
页面类型
@=@title # 可选
页面标题
@=@summary # 必选
页面内容一句话总结
@=@content # 可选
内容的详细解析
@=@chart # 可选
* 图表：图表标题1

图表内容
---
* 图表：图表概述2

图表内容
@=@table # 可选
* 表: 表格标题1

表格 1 内容
---
* 表: 表格标题2

表格 2 内容

注意：
1. 页面类型包括：标题、章节标题、目录、内容、版权信息、装饰、结束、其他。
2. 内容必须是完整、准确的，不能缺失任何内容，不能包含错误或编造的内容。
3. table 和 content 采用 md 格式。
4. 图表标题、表格标题尽量以 PPt 中的内容为准，也可以根据内容自行总结。
'''

class PPTXParserViaPDF(BasicParser):

    suffix = 'pptx'

    def __init__(self, file_path, root_path, cfg={}, title_prefix='%parent', logger=None, output_dir=''):
        # 检查文件类型
        if not file_path.lower().endswith('.pptx'):
            raise ValueError("file type error, not a pptx file")

        # 获取图像识别模型的相关算法配置
        self.img_parse_url = cfg['IMG_RECONGNIZE_MODEL']['url']
        self.img_parse_key = cfg['IMG_RECONGNIZE_MODEL']['api_key']
        self.img_parse_model = cfg['IMG_RECONGNIZE_MODEL']['model_name']
        self.openai_client = OpenAI(api_key=self.img_parse_key, base_url=self.img_parse_url)

        super().__init__(file_path, root_path, cfg, title_prefix, logger, output_dir)


    def copy_ppt_with_format(self, src_presentation, output_ppt_path):

        """带格式复制PPT到临时文件"""
        powerpoint = comtypes.client.CreateObject("Powerpoint.Application")
        powerpoint.Visible = 1  # 必须可见才能执行格式复制
        
        try:
            # 打开源文件
            # src_presentation = powerpoint.Presentations.Open(os.path.abspath(input_ppt_path))
            
            # 创建新演示文稿
            dest_presentation = powerpoint.Presentations.Add()
            
            # 复制每一页并保留格式
            for i in range(1, src_presentation.Slides.Count + 1):
                src_slide = src_presentation.Slides(i)
                src_slide.Copy()
                
                # 使用PasteSpecial确保格式保留
                dest_presentation.Slides.Paste()  # 粘贴到新PPT
                # dest_presentation.Windows(1).View.PasteSpecial(DataType=1)  # 2 = ppPasteDefault
                # dest_presentation.CommandBars.ExecuteMso("PasteSourceFormatting")
                
                # 添加延迟确保复制完成
                time.sleep(0.5)
            
            # 保存新文件
            dest_presentation.SaveAs(os.path.abspath(output_ppt_path))
            print(f"已带格式保存临时PPT到: {output_ppt_path}")
            return dest_presentation
            
        except Exception as e:
            print(f"复制过程中出错: {str(e)}")
        finally:
            pass
            # 确保关闭所有文档
            # if 'src_presentation' in locals():
            #     src_presentation.Close()
            # if 'dest_presentation' in locals():
            #     dest_presentation.Close()
            # powerpoint.Quit()
    

    def ppt_to_pdf(self, pdf_file_path, tmp_dir):

        if sys.platform.startswith('win'):

            powerpoint = comtypes.client.CreateObject("Powerpoint.Application")
            powerpoint.Visible = 1
            
            ppt = powerpoint.Presentations.Open(self.file_path, ReadOnly=False)
            try:
                ppt.SaveAs(pdf_file_path, 32)  # 32表示PDF格式
            except Exception as e:
                tmp_ppt = self._copy_ppt_with_format(ppt, 'tmp.pptx')
                tmp_ppt.SaveAs(pdf_file_path, 32)
                tmp_ppt.Close()

                os.remove('tmp.pptx')
            
            ppt.Close()
            powerpoint.Quit()

        ## 如果是 linux，使用 libreoffice 库
        elif sys.platform.startswith('linux') or sys.platform.startswith('linux'):
            import subprocess
            try:
                subprocess.run(['libreoffice', '--headless', '--convert-to', 'pdf', self.file_path, '--outdir', tmp_dir])
            except FileNotFoundError:
                raise FileNotFoundError("LibreOffice 未安装，请先安装 LibreOffice")
        ## 如果是 mac系统，使用 libreoffice 库
        elif sys.platform.startswith('darwin'):
            libreoffice_path = self.cfg['RUNTIME']['libreoffice_path']
            import subprocess
            try:
                subprocess.run([libreoffice_path, '--headless', '--convert-to', 'pdf', self.file_path, '--outdir', tmp_dir])
            except FileNotFoundError:
                raise FileNotFoundError("LibreOffice 未安装，请先安装 LibreOffice")
        
        self.logger.info(f'pdf file generated: {pdf_file_path}')


    def pdf_to_images(self, pdf_file_path, tmp_dir):
        # 打开 PDF 文件
        pdf_file = fitz.open(pdf_file_path)
        # 逐页解析 PDF 文件
        for pg in range(pdf_file.page_count):
            page = pdf_file[pg]
            pix = page.get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            # pg 转 4 位 str
            pg_str = str(pg+1).zfill(4)
            img.save(os.path.join(tmp_dir, f"{pg_str}.jpg"))  # 保存截图为 jpg 文件

        self.logger.info(f'pdf file converted to images, {pdf_file.page_count+1} pictures in total: {tmp_dir}')
    

    def _parse_llm_response(self, text, position_in_file):
        result = {}
        k = ''
        for l in text.split('\n'):
            if l.startswith('@=@'):
                if k != '':
                    result[k] = '\n'.join(result[k])
                k = l[3:]
                result[k] = []
            else:
                result[k].append(l)
        result[k] = '\n'.join(result[k])

        # 内容解析
        if 'title' in result.keys():
            result['simple_title'] = result['title']
        else:
            result['simple_title'] = result['summary']

        position = f'{self.knowledge_path}: {position_in_file}'
        content = []
        if 'content' in result.keys():
            content.append(result['content'])
        if 'chart' in result.keys():
            content.append(result['chart'])
        if 'table' in result.keys():
            content.append(result['table'])
        if content == []:
            content = result['summary']
        
        content = f'\n@section: {position}\n\n' + '\n\n'.join(content) + '\n@endsection\n'
        result['content'] = content

        return result

    
    def get_summary(self, img_path, position_in_file):
        # 调用 OpenAI 的 API 进行图像识别
       
        b64_img = base64.b64encode(open(img_path, 'rb').read()).decode()
        response = self.openai_client.chat.completions.create(
            model=self.img_parse_model,
            messages=[
                {"role": "system", "content": ppt_parse_prompt},
                {"role": "user", "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}
                    },
                ]}
            ]
        )
        
        try:
            result = response.choices[0].message.content
            result_dict = self._parse_llm_response(result, position_in_file)
            return result_dict
        except Exception as e:
            self.logger.error(f'image path: {img_path} parse error')
            self.logger.error(f'error: {e}')
            self.logger.error(f'response: {result}')
    
        
    def parse(self):

        # 生成临时文件夹
        tmp_dir = self.temp_dir
        
        file_basename = os.path.basename(self.file_path)
        file_rootname = os.path.splitext(file_basename)[0]
        # 把 pptx 文件转换成 pdf 文件
        pdf_file_path = os.path.join(tmp_dir, file_rootname + '.pdf')
        self.ppt_to_pdf(pdf_file_path, tmp_dir)
        
        # 把 pdf 文件转换成图片文件
        self.pdf_to_images(pdf_file_path, tmp_dir)

        # 解析 tmp_dir 下 png 结尾的文件
        img_files = [x  for x in os.listdir(tmp_dir) if x.endswith('.jpg')]
        # 按照文件名排序
        img_files.sort()

        # 设置标题前缀
        file_title = ''
        chapter_title = ''
        content_title = ''

        for img_file in img_files:

            img_path = os.path.join(tmp_dir, img_file)
            result = self.get_summary(img_path, f'page {img_file.split(".")[0]}')

            if result is None:
                self.logger.warning(f'page {img_file.split(".")[0]}: parse error, skip')
                continue

            if result['page_type'] == '标题':
                file_title = result['title']
            elif result['page_type'] == '章节标题':
                chapter_title = result['title']
            elif result['page_type'] == '目录':
                pass
            elif result['page_type'] == '内容':

                if content_title == result['title']:
                    # 找到 self.qa_info 中和 content_title 相同的元素，把 content 合并
                    for i in range(len(self.qa_info)):
                        if self.qa_info[i]['title'] == result['title']:
                            self.qa_info[i]['content'] += '\n' + result['content']
                            break
                else:
                    content_title = result['title']
                    title_list = [ x for x in [self.title_prefix, file_title, chapter_title, result['title']] if x != '']
                    result['full_title'] = '-'.join(title_list)
                    self.qa_info.append(result)
            else:
                self.logger.warning(f'page {img_file.split(".")[0]}: {result["page_type"]} not included in qa result')


            self.logger.info(f'page {img_file.split(".")[0]}: {result}')


        return self.qa_info
