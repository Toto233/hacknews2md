import sys
import urllib3
from summarize_news import get_article_content

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def test_article_fetch():
    """测试文章获取功能"""
    # 设置控制台编码
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
    
    # 测试用例
    test_cases = [
        # {
        #     'title': 'I Tested the Weirdest Phones on the Internet.',
        #     'url': 'https://www.youtube.com/watch?v=T_3O1FCxS5Q'
        # },
        {
            'title': 'How to get a full transcript of YouTube videos in 2025',
            'url': 'https://www.descript.com/blog/article/transcript-of-youtube-videos'
        }
    ]
    
    for test_case in test_cases:
        print(f"\n测试文章: {test_case['title']}")
        print(f"URL: {test_case['url']}")
        
        # 获取文章内容和图片
        content, image_urls, image_paths = get_article_content(test_case['url'], test_case['title'])
        
        if content:
            # 打印文章预览
            preview = content[:500] + '...' if len(content) > 500 else content
            print(f"\n文章预览:\n{preview}")
            
            # 打印图片信息
            if image_urls:
                print(f"\n找到图片:")
                for url, path in zip(image_urls, image_paths):
                    print(f"URL: {url}")
                    print(f"保存路径: {path}")
            else:
                print("\n未找到合适的图片")
        else:
            print("\n获取文章内容失败")

if __name__ == '__main__':
    test_article_fetch()