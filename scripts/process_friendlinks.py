#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import requests
import feedparser
import time
from datetime import datetime
from dateutil import parser as date_parser
from pathlib import Path
import re
import socket

GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
REPO = os.environ.get('GITHUB_REPOSITORY')
ISSUE_NUMBER = os.environ.get('ISSUE_NUMBER')
EVENT_NAME = os.environ.get('EVENT_NAME')
OUTPUT_PATH = os.environ.get('OUTPUT_PATH', 'output')

DATA_FILE = os.path.join(OUTPUT_PATH, 'v2/data.json')
HEADERS = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}

def check_website(url, timeout=15):
    """检查网站是否可访问 - 增强版本"""
    # 添加常见的 User-Agent 头，避免被某些网站屏蔽
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        print(f"尝试访问网站: {url}")
        response = requests.get(
            url, 
            timeout=timeout, 
            allow_redirects=True,
            headers=headers,
            verify=False  # 跳过 SSL 验证，避免证书问题
        )
        print(f"网站状态码: {response.status_code}")
        return response.status_code == 200
    except requests.exceptions.Timeout:
        print(f"网站访问超时: {url} (超过 {timeout} 秒)")
        return False
    except requests.exceptions.SSLError as e:
        print(f"SSL 证书错误 {url}: {str(e)}")
        # SSL 错误时尝试不验证证书
        try:
            response = requests.get(
                url, 
                timeout=timeout, 
                allow_redirects=True,
                headers=headers,
                verify=False
            )
            print(f"忽略SSL证书后状态码: {response.status_code}")
            return response.status_code == 200
        except Exception as e2:
            print(f"忽略SSL后仍然失败: {str(e2)}")
            return False
    except Exception as e:
        print(f"检查网站失败 {url}: {str(e)}")
        return False

def check_website_alternative(url, timeout=10):
    """备用检查方法 - 通过 DNS 解析和端口连接"""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        hostname = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        
        print(f"尝试 DNS 解析: {hostname}")
        ip = socket.gethostbyname(hostname)
        print(f"DNS 解析成功: {hostname} -> {ip}")
        
        # 尝试建立 TCP 连接
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        
        if result == 0:
            print(f"TCP 连接成功: {hostname}:{port}")
            return True
        else:
            print(f"TCP 连接失败: {hostname}:{port} (错误码: {result})")
            return False
    except Exception as e:
        print(f"备用检查方法失败: {str(e)}")
        return False

def check_website_robust(url):
    """健壮的网站检查"""
    print(f"\n开始健壮性检查: {url}")
    
    # 方法1: 直接 HTTP 请求
    if check_website(url):
        print("✓ 方法1: 直接请求成功")
        return True
    
    # 方法2: 备用检查
    print("方法1失败，尝试备用检查方法...")
    if check_website_alternative(url):
        print("✓ 方法2: 备用检查成功")
        return True
    
    # 方法3: 尝试不同的超时时间
    print("方法2失败，尝试增加超时时间...")
    if check_website(url, timeout=30):
        print("✓ 方法3: 增加超时后成功")
        return True
    
    print("✗ 所有检查方法都失败")
    return False

def fetch_rss_posts(feed_url, max_posts=3):
    """抓取 RSS 文章"""
    try:
        print(f"抓取 RSS: {feed_url}")
        # 添加 User-Agent 避免被屏蔽
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # 使用 requests 获取内容，然后交给 feedparser 解析
        response = requests.get(feed_url, headers=headers, timeout=15, verify=False)
        response.raise_for_status()
        
        feed = feedparser.parse(response.content)
        posts = []

        for entry in feed.entries[:max_posts]:
            published = None
            if hasattr(entry, 'published'):
                published = entry.published
            elif hasattr(entry, 'updated'):
                published = entry.updated

            # 解析发布时间
            published_time = ""
            if published:
                try:
                    dt = date_parser.parse(published)
                    published_time = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    published_time = published

            posts.append({
                'title': entry.title if hasattr(entry, 'title') else '',
                'link': entry.link if hasattr(entry, 'link') else '',
                'published': published_time
            })

        print(f"成功抓取 {len(posts)} 篇文章")
        return posts
    except Exception as e:
        print(f"抓取 RSS 失败 {feed_url}: {str(e)}")
        return []

def parse_issue_body(body):
    """解析 Issue 内容"""
    print(f"\n=== 开始解析 Issue 内容 ===")
    print(f"原始内容长度: {len(body)} 字符")
    print(f"原始内容预览:\n{body[:500]}\n")

    data = {}

    # 匹配表单格式（GitHub Issue Form）
    patterns = {
        'title': r'### 网站名称\s*\n\s*([^\n]+)',
        'url': r'### 网站地址\s*\n\s*([^\n]+)',
        'avatar': r'### 头像地址\s*\n\s*([^\n]+)',
        'description': r'### 网站描述\s*\n\s*([^\n]+)',
        'feed': r'### RSS 订阅地址\s*\n\s*([^\n]+)'
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, body, re.MULTILINE)
        if match:
            value = match.group(1).strip()
            data[key] = value
            print(f"✓ 成功解析 {key}: {value}")
        else:
            print(f"✗ 未找到 {key}")

    print(f"\n解析结果: {json.dumps(data, ensure_ascii=False, indent=2)}")
    print("=== Issue 解析完成 ===\n")

    return data

def get_all_issues():
    """获取所有友链申请的 Issue"""
    url = f'https://api.github.com/repos/{REPO}/issues'
    params = {
        'labels': '友链申请',
        'state': 'open',
        'per_page': 100
    }

    try:
        response = requests.get(url, headers=HEADERS, params=params)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"获取 Issues 失败: {str(e)}")
        return []

def comment_on_issue(issue_number, comment):
    """在 Issue 上添加评论"""
    url = f'https://api.github.com/repos/{REPO}/issues/{issue_number}/comments'
    data = {'body': comment}

    try:
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"评论失败: {str(e)}")
        return False

def add_label_to_issue(issue_number, label):
    """给 Issue 添加标签"""
    url = f'https://api.github.com/repos/{REPO}/issues/{issue_number}/labels'
    data = {'labels': [label]}

    try:
        response = requests.post(url, headers=HEADERS, json=data)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"添加标签失败: {str(e)}")
        return False

def load_data():
    """加载现有数据"""
    Path(DATA_FILE).parent.mkdir(parents=True, exist_ok=True)

    if Path(DATA_FILE).exists():
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        return {'version': 'v2', 'content': []}

def save_data(data):
    """保存数据"""
    # 按最新文章发布时间排序
    for item in data['content']:
        if item['posts']:
            try:
                # 解析第一篇文章的发布时间
                latest_time = datetime.strptime(item['posts'][0]['published'], '%Y-%m-%d %H:%M')
                item['_sort_time'] = latest_time.timestamp()
            except:
                item['_sort_time'] = 0
        else:
            item['_sort_time'] = 0

    # 倒序排序（最新的在前面）
    data['content'].sort(key=lambda x: x.get('_sort_time', 0), reverse=True)

    # 删除排序用的临时字段
    for item in data['content']:
        if '_sort_time' in item:
            del item['_sort_time']

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def process_single_issue(issue, data):
    """处理单个 Issue"""
    issue_number = issue['number']
    body = issue['body'] or ''

    print(f"\n{'='*60}")
    print(f"开始处理 Issue #{issue_number}")
    print(f"Issue 标题: {issue.get('title', 'N/A')}")
    print(f"Issue 标签: {[label['name'] for label in issue.get('labels', [])]}")
    print(f"{'='*60}")

    # 解析 Issue 内容
    info = parse_issue_body(body)

    if not all(k in info for k in ['title', 'url', 'feed']):
        missing = [k for k in ['title', 'url', 'feed'] if k not in info]
        print(f"❌ Issue #{issue_number} 信息不完整，缺少字段: {missing}")
        comment_on_issue(
            issue_number,
            f"❌ 友链信息不完整\n\n缺少以下必需字段: {', '.join(missing)}\n\n请检查 Issue 内容格式是否正确。\n\n检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return False

    print(f"\n✓ Issue 信息解析成功")

    # 检查网站是否在线 - 使用健壮性检查
    print(f"\n正在检查网站: {info['url']}")
    website_online = check_website_robust(info['url'])
    
    if not website_online:
        print(f"❌ 网站离线: {info['url']}")
        comment_on_issue(
            issue_number,
            f"⚠️ 网站访问检查失败\n\n在 GitHub Actions 环境中无法访问 {info['url']}，这可能是由于网络限制。\n\n但我们会继续处理 RSS 订阅源。如果 RSS 可用，友链仍会被添加。\n\n检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        # 不立即返回，继续处理 RSS
        add_label_to_issue(issue_number, '访问受限')
    else:
        print(f"✓ 网站在线")
        add_label_to_issue(issue_number, '在线')

    # 抓取 RSS
    print(f"\n正在抓取 RSS: {info['feed']}")
    posts = fetch_rss_posts(info['feed'])

    if not posts:
        print(f"⚠️ RSS 抓取失败: {info['feed']}")
        comment_on_issue(
            issue_number,
            f"❌ RSS 订阅源访问失败\n\n无法获取 {info['feed']} 的内容，请检查 RSS 地址是否正确。\n\n检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        # RSS 失败则整个申请失败
        return False

    print(f"✓ RSS 抓取成功，获取 {len(posts)} 篇文章")

    # 查找是否已存在
    existing_index = None
    for i, item in enumerate(data['content']):
        if item['issue_number'] == issue_number:
            existing_index = i
            break

    # 构建友链数据
    friend_data = {
        'title': info['title'],
        'url': info['url'],
        'icon': info.get('avatar', ''),
        'description': info.get('description', ''),
        'feed': info['feed'],
        'posts': posts,
        'issue_number': issue_number,
        'labels': [label['name'] for label in issue.get('labels', [])],
        'last_checked': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'online': website_online  # 记录网站检查状态
    }

    # 添加或更新
    if existing_index is not None:
        data['content'][existing_index] = friend_data
        print(f"\n✓ 更新友链: {info['title']}")
        comment_on_issue(
            issue_number,
            f"✅ 友链已更新\n\n- 网站名称: {info['title']}\n- 网站状态: {'在线' if website_online else '访问受限'}\n- 最新文章数: {len(posts)}\n\n更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    else:
        data['content'].append(friend_data)
        print(f"\n✓ 新增友链: {info['title']}")
        comment_on_issue(
            issue_number,
            f"✅ 友链申请已通过\n\n欢迎加入友链！\n\n- 网站名称: {info['title']}\n- 网站状态: {'在线' if website_online else '访问受限'}\n- 最新文章数: {len(posts)}\n\n审核时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        add_label_to_issue(issue_number, '已通过')

    print(f"{'='*60}\n")
    return True

def main():
    print("\n" + "="*60)
    print("友链处理系统启动")
    print("="*60)
    print(f"事件类型: {EVENT_NAME}")
    print(f"仓库: {REPO}")
    print(f"输出路径: {OUTPUT_PATH}")
    print(f"数据文件: {DATA_FILE}")
    print("="*60 + "\n")

    # 禁用 SSL 警告
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    data = load_data()
    print(f"当前友链数量: {len(data['content'])}\n")

    if EVENT_NAME == 'issues' and ISSUE_NUMBER:
        # 处理单个 Issue
        print(f"触发类型: Issue 事件 (#{ISSUE_NUMBER})")
        url = f'https://api.github.com/repos/{REPO}/issues/{ISSUE_NUMBER}'
        try:
            response = requests.get(url, headers=HEADERS)
            response.raise_for_status()
            issue = response.json()

            print(f"\nIssue 基本信息:")
            print(f"  - 标题: {issue.get('title', 'N/A')}")
            print(f"  - 状态: {issue.get('state', 'N/A')}")
            print(f"  - 标签: {[label['name'] for label in issue.get('labels', [])]}")

            labels = [label['name'] for label in issue.get('labels', [])]
            if '友链申请' in labels:
                print(f"\n✓ 找到友链申请标签，开始处理...")
                process_single_issue(issue, data)
            else:
                print(f"\n✗ 未找到'友链申请'标签，跳过处理")
                print(f"  当前标签: {labels}")
        except Exception as e:
            print(f"\n❌ 获取或处理 Issue 失败: {str(e)}")
            import traceback
            traceback.print_exc()
    else:
        # 定时任务：处理所有 Issue
        print(f"触发类型: 定时任务或手动触发")
        issues = get_all_issues()
        print(f"\n找到 {len(issues)} 个待处理的友链申请\n")

        success_count = 0
        fail_count = 0

        for issue in issues:
            try:
                if process_single_issue(issue, data):
                    success_count += 1
                else:
                    fail_count += 1
                time.sleep(2)  # 避免 API 限流
            except Exception as e:
                fail_count += 1
                print(f"❌ 处理 Issue #{issue['number']} 时出错: {str(e)}")
                import traceback
                traceback.print_exc()

        print(f"\n处理统计:")
        print(f"  - 成功: {success_count}")
        print(f"  - 失败: {fail_count}")

    # 保存数据
    print(f"\n正在保存数据到: {DATA_FILE}")
    save_data(data)
    print(f"✓ 数据保存成功")

    print("\n" + "="*60)
    print("友链处理完成")
    print(f"最终友链数量: {len(data['content'])}")
    print("="*60 + "\n")

if __name__ == '__main__':
    main()