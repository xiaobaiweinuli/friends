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

def check_website(url, timeout=10):
    """检查网站是否可访问"""
    try:
        response = requests.get(url, timeout=timeout, allow_redirects=True)
        return response.status_code == 200
    except Exception as e:
        print(f"检查网站失败 {url}: {str(e)}")
        return False

def fetch_rss_posts(feed_url, max_posts=3):
    """抓取 RSS 文章"""
    try:
        feed = feedparser.parse(feed_url)
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
        
        return posts
    except Exception as e:
        print(f"抓取 RSS 失败 {feed_url}: {str(e)}")
        return []

def parse_issue_body(body):
    """解析 Issue 内容"""
    data = {}
    
    # 匹配表单格式
    patterns = {
        'title': r'### 网站名称\s*([^\n]+)',
        'url': r'### 网站地址\s*([^\n]+)',
        'avatar': r'### 头像地址\s*([^\n]+)',
        'description': r'### 网站描述\s*([^\n]+)',
        'feed': r'### RSS 订阅地址\s*([^\n]+)'
    }
    
    for key, pattern in patterns.items():
        match = re.search(pattern, body)
        if match:
            data[key] = match.group(1).strip()
    
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
    
    print(f"\n处理 Issue #{issue_number}")
    
    # 解析 Issue 内容
    info = parse_issue_body(body)
    
    if not all(k in info for k in ['title', 'url', 'feed']):
        print(f"Issue #{issue_number} 信息不完整")
        comment_on_issue(issue_number, "❌ 友链信息不完整，请检查是否填写了所有必需字段。")
        return False
    
    # 检查网站是否在线
    print(f"检查网站: {info['url']}")
    if not check_website(info['url']):
        print(f"网站离线: {info['url']}")
        comment_on_issue(
            issue_number,
            f"❌ 网站访问失败\n\n无法访问 {info['url']}，请检查网站是否正常运行。\n\n检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        add_label_to_issue(issue_number, '离线')
        return False
    
    # 抓取 RSS
    print(f"抓取 RSS: {info['feed']}")
    posts = fetch_rss_posts(info['feed'])
    
    if not posts:
        print(f"RSS 抓取失败: {info['feed']}")
        comment_on_issue(
            issue_number,
            f"⚠️ RSS 订阅源访问失败\n\n无法获取 {info['feed']} 的内容，请检查 RSS 地址是否正确。\n\n检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return False
    
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
        'labels': [label['name'] for label in issue.get('labels', [])]
    }
    
    # 添加或更新
    if existing_index is not None:
        data['content'][existing_index] = friend_data
        print(f"更新友链: {info['title']}")
    else:
        data['content'].append(friend_data)
        print(f"新增友链: {info['title']}")
        comment_on_issue(
            issue_number,
            f"✅ 友链申请已通过\n\n欢迎加入友链！\n\n- 网站名称: {info['title']}\n- 网站地址: {info['url']}\n- 最新文章数: {len(posts)}\n\n审核时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        add_label_to_issue(issue_number, '已通过')
    
    return True

def main():
    print("开始处理友链...")
    print(f"事件类型: {EVENT_NAME}")
    
    data = load_data()
    
    if EVENT_NAME == 'issues' and ISSUE_NUMBER:
        # 处理单个 Issue
        url = f'https://api.github.com/repos/{REPO}/issues/{ISSUE_NUMBER}'
        response = requests.get(url, headers=HEADERS)
        if response.status_code == 200:
            issue = response.json()
            if '友链申请' in [label['name'] for label in issue.get('labels', [])]:
                process_single_issue(issue, data)
    else:
        # 定时任务：处理所有 Issue
        issues = get_all_issues()
        print(f"找到 {len(issues)} 个友链申请")
        
        for issue in issues:
            try:
                process_single_issue(issue, data)
                time.sleep(1)  # 避免 API 限流
            except Exception as e:
                print(f"处理 Issue #{issue['number']} 时出错: {str(e)}")
    
    # 保存数据
    save_data(data)
    print("\n处理完成！")
    print(f"当前友链数量: {len(data['content'])}")

if __name__ == '__main__':
    main()
