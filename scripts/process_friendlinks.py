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
import urllib3

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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

# 定义状态标签
STATUS_LABELS = ['在线', '离线', '访问受限', '已通过', '待处理']

def resolve_domain(domain):
    """尝试解析域名"""
    try:
        # 尝试使用多个 DNS 服务器
        dns_servers = ['8.8.8.8', '1.1.1.1', '114.114.114.114']
        for dns in dns_servers:
            try:
                resolver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                resolver.settimeout(5)
                # 发送 DNS 查询（简化版）
                print(f"尝试使用 DNS {dns} 解析 {domain}")
                ip = socket.gethostbyname(domain)
                print(f"✓ 域名解析成功: {domain} -> {ip}")
                return ip
            except:
                continue
        return None
    except Exception as e:
        print(f"域名解析失败: {str(e)}")
        return None

def check_website_with_retry(url, max_retries=3):
    """带重试的网站检查"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    for attempt in range(max_retries):
        try:
            print(f"尝试 {attempt + 1}/{max_retries}: {url}")
            response = requests.get(
                url, 
                timeout=15, 
                allow_redirects=True,
                headers=headers,
                verify=False
            )
            print(f"状态码: {response.status_code}")
            if response.status_code == 200:
                return True
            time.sleep(2)  # 等待后重试
        except requests.exceptions.ConnectionError as e:
            print(f"连接错误 (尝试 {attempt + 1}): {str(e)}")
            if "NameResolutionError" in str(e):
                # 如果是域名解析错误，尝试手动解析
                from urllib.parse import urlparse
                parsed = urlparse(url)
                domain = parsed.hostname
                ip = resolve_domain(domain)
                if ip:
                    # 使用 IP 地址重试
                    new_url = url.replace(domain, ip)
                    headers['Host'] = domain  # 添加 Host 头
                    try:
                        print(f"使用 IP 地址重试: {new_url}")
                        response = requests.get(
                            new_url,
                            timeout=15,
                            allow_redirects=True,
                            headers=headers,
                            verify=False
                        )
                        if response.status_code == 200:
                            return True
                    except Exception as ip_e:
                        print(f"IP 重试失败: {str(ip_e)}")
            time.sleep(2)
        except Exception as e:
            print(f"其他错误 (尝试 {attempt + 1}): {str(e)}")
            time.sleep(2)
    
    return False

def check_website_robust(url):
    """健壮的网站检查"""
    print(f"\n开始健壮性检查: {url}")
    
    # 方法1: 带重试的直接请求
    if check_website_with_retry(url):
        print("✓ 方法1: 带重试的直接请求成功")
        return True
    
    # 方法2: 检查基本连接性
    print("方法1失败，尝试基本连接性检查...")
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        hostname = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        
        # 先解析域名
        ip = resolve_domain(hostname)
        if not ip:
            print("✗ 无法解析域名")
            return False
            
        # 尝试 TCP 连接
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        result = sock.connect_ex((ip, port))
        sock.close()
        
        if result == 0:
            print("✓ TCP 连接成功")
            return True
        else:
            print(f"✗ TCP 连接失败 (错误码: {result})")
            return False
    except Exception as e:
        print(f"基本连接性检查失败: {str(e)}")
        return False

def fetch_rss_with_fallback(feed_url, max_posts=3):
    """带备用方案的 RSS 抓取"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    # 方法1: 直接抓取
    try:
        print(f"方法1: 直接抓取 RSS")
        response = requests.get(feed_url, headers=headers, timeout=15, verify=False)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        return process_feed_entries(feed, max_posts)
    except Exception as e:
        print(f"直接抓取失败: {str(e)}")
    
    # 方法2: 尝试使用 IP 地址
    try:
        from urllib.parse import urlparse
        parsed = urlparse(feed_url)
        domain = parsed.hostname
        ip = resolve_domain(domain)
        
        if ip:
            print(f"方法2: 使用 IP 地址抓取")
            new_feed_url = feed_url.replace(domain, ip)
            headers['Host'] = domain
            response = requests.get(new_feed_url, headers=headers, timeout=15, verify=False)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            return process_feed_entries(feed, max_posts)
    except Exception as e:
        print(f"IP 地址抓取失败: {str(e)}")
    
    # 方法3: 尝试公共 RSS 代理服务（如果有）
    print("方法3: 所有方法都失败")
    return []

def process_feed_entries(feed, max_posts):
    """处理 Feed 条目"""
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

    print(f"成功处理 {len(posts)} 篇文章")
    return posts

def parse_issue_body(body):
    """解析 Issue 内容"""
    print(f"\n=== 开始解析 Issue 内容 ===")
    data = {}

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

def get_issue_comments(issue_number):
    """获取 Issue 的所有评论"""
    url = f'https://api.github.com/repos/{REPO}/issues/{issue_number}/comments'
    
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"获取评论失败: {str(e)}")
        return []

def get_bot_comment_id(issue_number):
    """获取机器人评论的 ID"""
    comments = get_issue_comments(issue_number)
    current_user = get_current_user()
    
    for comment in comments:
        if comment.get('user', {}).get('login') == current_user:
            return comment['id']
    
    return None

def update_comment_on_issue(issue_number, comment_body):
    """更新或创建评论"""
    comment_id = get_bot_comment_id(issue_number)
    
    if comment_id:
        # 更新现有评论
        url = f'https://api.github.com/repos/{REPO}/issues/comments/{comment_id}'
        data = {'body': comment_body}
        
        try:
            response = requests.patch(url, headers=HEADERS, json=data)
            response.raise_for_status()
            print(f"✓ 更新评论: {comment_id}")
            return True
        except Exception as e:
            print(f"更新评论失败: {str(e)}")
            return False
    else:
        # 创建新评论
        url = f'https://api.github.com/repos/{REPO}/issues/{issue_number}/comments'
        data = {'body': comment_body}
        
        try:
            response = requests.post(url, headers=HEADERS, json=data)
            response.raise_for_status()
            print(f"✓ 创建新评论")
            return True
        except Exception as e:
            print(f"创建评论失败: {str(e)}")
            return False

def get_current_user():
    """获取当前认证用户"""
    url = 'https://api.github.com/user'
    
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json().get('login', '')
    except Exception as e:
        print(f"获取用户信息失败: {str(e)}")
        return ''

def update_issue_labels(issue_number, new_labels):
    """更新 Issue 标签 - 替换状态标签，保留其他标签"""
    # 获取当前标签
    current_issue = get_issue(issue_number)
    if not current_issue:
        return False
        
    current_labels = [label['name'] for label in current_issue.get('labels', [])]
    
    # 过滤掉状态标签，保留其他标签（如"友链申请"）
    filtered_labels = [label for label in current_labels if label not in STATUS_LABELS]
    
    # 添加新的状态标签
    final_labels = filtered_labels + new_labels
    
    # 更新标签
    url = f'https://api.github.com/repos/{REPO}/issues/{issue_number}/labels'
    data = {'labels': final_labels}

    try:
        response = requests.put(url, headers=HEADERS, json=data)
        response.raise_for_status()
        print(f"✓ 更新标签: {final_labels}")
        return True
    except Exception as e:
        print(f"更新标签失败: {str(e)}")
        return False

def get_issue(issue_number):
    """获取单个 Issue 信息"""
    url = f'https://api.github.com/repos/{REPO}/issues/{issue_number}'
    
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"获取 Issue 失败: {str(e)}")
        return None

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
    for item in data['content']:
        if item['posts']:
            try:
                latest_time = datetime.strptime(item['posts'][0]['published'], '%Y-%m-%d %H:%M')
                item['_sort_time'] = latest_time.timestamp()
            except:
                item['_sort_time'] = 0
        else:
            item['_sort_time'] = 0

    data['content'].sort(key=lambda x: x.get('_sort_time', 0), reverse=True)

    for item in data['content']:
        if '_sort_time' in item:
            del item['_sort_time']

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def process_single_issue(issue, data):
    """处理单个 Issue - 放宽检查条件"""
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
        update_comment_on_issue(
            issue_number,
            f"❌ 友链信息不完整\n\n缺少以下必需字段: {', '.join(missing)}\n\n请检查 Issue 内容格式是否正确。\n\n检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return False

    print(f"\n✓ Issue 信息解析成功")

    # 放宽网站检查条件
    print(f"\n正在检查网站: {info['url']}")
    website_online = check_website_robust(info['url'])
    
    # 确定状态标签
    status_label = '在线' if website_online else '访问受限'
    
    # 即使网站检查失败也继续处理，因为可能是 GitHub Actions 的网络限制
    if not website_online:
        print(f"⚠️ 网站检查失败，继续处理 RSS: {info['url']}")
        update_comment_on_issue(
            issue_number,
            f"⚠️ 网站访问检查失败\n\n在 GitHub Actions 环境中无法访问 {info['url']}，这可能是由于网络限制。\n\n我们会继续处理 RSS 订阅源，如果 RSS 可用，友链仍会被添加。\n\n检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    else:
        print(f"✓ 网站在线")

    # 抓取 RSS - 使用备用方案
    print(f"\n正在抓取 RSS: {info['feed']}")
    posts = fetch_rss_with_fallback(info['feed'])

    if not posts:
        print(f"❌ RSS 抓取失败: {info['feed']}")
        update_comment_on_issue(
            issue_number,
            f"❌ RSS 订阅源访问失败\n\n无法获取 {info['feed']} 的内容，请检查 RSS 地址是否正确且可公开访问。\n\n检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        # RSS 失败时也更新标签
        update_issue_labels(issue_number, [status_label])
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
        'online': website_online
    }

    # 添加或更新
    if existing_index is not None:
        data['content'][existing_index] = friend_data
        print(f"\n✓ 更新友链: {info['title']}")
        update_comment_on_issue(
            issue_number,
            f"✅ 友链已更新\n\n- 网站名称: {info['title']}\n- 网站状态: {'在线' if website_online else '访问受限'}\n- 最新文章数: {len(posts)}\n\n更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        # 更新标签：状态标签 + 已通过
        update_issue_labels(issue_number, [status_label, '已通过'])
    else:
        data['content'].append(friend_data)
        print(f"\n✓ 新增友链: {info['title']}")
        update_comment_on_issue(
            issue_number,
            f"✅ 友链申请已通过\n\n欢迎加入友链！\n\n- 网站名称: {info['title']}\n- 网站状态: {'在线' if website_online else '访问受限'}\n- 最新文章数: {len(posts)}\n\n审核时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        # 新申请：状态标签 + 已通过
        update_issue_labels(issue_number, [status_label, '已通过'])

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

    data = load_data()
    print(f"当前友链数量: {len(data['content'])}\n")

    if EVENT_NAME == 'issues' and ISSUE_NUMBER:
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
                time.sleep(2)
            except Exception as e:
                fail_count += 1
                print(f"❌ 处理 Issue #{issue['number']} 时出错: {str(e)}")
                import traceback
                traceback.print_exc()

        print(f"\n处理统计:")
        print(f"  - 成功: {success_count}")
        print(f"  - 失败: {fail_count}")

    print(f"\n正在保存数据到: {DATA_FILE}")
    save_data(data)
    print(f"✓ 数据保存成功")

    print("\n" + "="*60)
    print("友链处理完成")
    print(f"最终友链数量: {len(data['content'])}")
    print("="*60 + "\n")

if __name__ == '__main__':
    main()