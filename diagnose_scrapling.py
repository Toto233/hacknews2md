"""
诊断 Scrapling 安装和 lxml 版本冲突问题
"""

import sys
import io

# Windows 下设置 UTF-8 编码输出
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

print("=" * 60)
print("Scrapling 诊断工具")
print("=" * 60)

# 检查 lxml 版本
print("\n1. 检查 lxml 版本:")
try:
    import lxml
    print(f"   [OK] lxml 已安装")
    print(f"   版本: {lxml.__version__}")
except ImportError as e:
    print(f"   [FAIL] lxml 未安装: {e}")

# 检查 crawl4ai 要求
print("\n2. 检查 crawl4ai 要求:")
try:
    import crawl4ai
    print(f"   [OK] crawl4ai 已安装")
    print(f"   版本: {crawl4ai.__version__}")

    # 检查依赖要求
    try:
        import pkg_resources
        dist = pkg_resources.get_distribution('crawl4ai')
        print(f"   要求: lxml~=5.3")
    except:
        pass
except ImportError as e:
    print(f"   [FAIL] crawl4ai 未安装: {e}")

# 检查 scrapling
print("\n3. 检查 Scrapling:")
try:
    import scrapling
    print(f"   [OK] Scrapling 已安装")
    print(f"   版本: {scrapling.__version__}")

    # 尝试导入 Fetcher
    try:
        from scrapling.fetchers import Fetcher
        print(f"   [OK] Fetcher 导入成功")
    except Exception as e:
        print(f"   [FAIL] Fetcher 导入失败: {e}")

    # 尝试导入 Spider
    try:
        from scrapling.spiders import Spider, Response
        print(f"   [OK] Spider 导入成功")
    except Exception as e:
        print(f"   [FAIL] Spider 导入失败: {e}")

except ImportError as e:
    print(f"   [FAIL] Scrapling 未安装: {e}")

# 测试基本的 Fetcher 功能
print("\n4. 测试 Scrapling 基本功能:")
try:
    from scrapling.fetchers import Fetcher

    test_url = "https://example.com"
    print(f"   测试 URL: {test_url}")

    try:
        page = Fetcher.get(test_url)
        print(f"   [OK] 抓取成功!")
        print(f"   内容长度: {len(page.text)} 字符")
    except Exception as e:
        print(f"   [FAIL] 抓取失败: {e}")

except Exception as e:
    print(f"   [FAIL] 测试失败: {e}")

# 给出建议
print("\n" + "=" * 60)
print("诊断结果和建议")
print("=" * 60)

import pkg_resources
try:
    lxml_version = pkg_resources.get_distribution('lxml').version
    if lxml_version.startswith('6.'):
        print("\n[警告] 检测到 lxml 6.x 版本")
        print("\n问题: crawl4ai 需要 lxml~=5.3，但 scrapling 安装了 lxml 6.0.2")
        print("\n解决方案选项:")
        print("1. 降级 lxml 到 5.3.x:")
        print("   pip install 'lxml>=5.3,<6.0'")
        print("\n2. 或者等待 crawl4ai 更新以支持 lxml 6.x")
        print("\n3. 或者使用虚拟环境隔离不同版本的依赖")
except:
    pass

print("\n" + "=" * 60)
