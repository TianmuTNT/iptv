import requests
import pandas as pd
import re
import os
import time
from concurrent.futures import ThreadPoolExecutor

# 配置参数
MAX_SOURCES_PER_CHANNEL = 10  # 每个频道保留源数
REQUEST_TIMEOUT = 5  # 源质量检测超时(秒)
THREAD_POOL = 10  # 并发检测线程数

# 直播源URL列表
urls = [
    "http://8.138.7.223/live.txt",
    "https://7337.kstore.space/twkj/tvzb.txt",
    "https://ghfast.top/https://raw.githubusercontent.com/tianya7981/jiekou/refs/heads/main/%E9%87%8E%E7%81%AB959",
    "http://tot.totalh.net/tttt.txt",
    "https://raw.githubusercontent.com/YanG-1989/m3u/main/Gather.m3u",
    "https://raw.githubusercontent.com/YueChan/Live/refs/heads/main/APTV.m3u",
    "https://raw.githubusercontent.com/Kimentanm/aptv/master/m3u/iptv.m3u",
    'https://raw.githubusercontent.com/BurningC4/Chinese-IPTV/master/TV-IPV4.m3u',
    "https://raw.githubusercontent.com/Ftindy/IPTV-URL/main/IPV6.m3u",
]

# 频道过滤正则
channel_pattern = re.compile(
    r'CCTV|卫视',
    re.IGNORECASE
)

# 协议识别正则
ipv4_pattern = re.compile(r'^https?://(\d{1,3}\.){3}\d{1,3}')
ipv6_pattern = re.compile(r'^https?://\[([a-fA-F0-9:]+)\]')

def fetch_streams_from_url(url):
    print(f"📡 正在抓取源: {url}")
    try:
        response = requests.get(url, timeout=10)
        response.encoding = 'utf-8'
        return response.text if response.status_code == 200 else None
    except Exception as e:
        print(f"❌ 抓取失败 {url}: {str(e)}")
        return None

def fetch_all_streams():
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = executor.map(fetch_streams_from_url, urls)
    return "\n".join(filter(None, results))

def parse_m3u(content):
    streams = []
    current = {}
    for line in content.splitlines():
        if line.startswith("#EXTINF"):
            current["meta"] = line
            current["name"] = re.search(r'tvg-name="([^"]+)"', line).group(1)
        elif line.startswith("http"):
            streams.append({
                "program_name": current.get("name", "未知频道"),
                "stream_url": line.strip(),
                "meta": current.get("meta", "")
            })
    return streams

def parse_txt(content):
    streams = []
    for line in content.splitlines():
        if match := re.match(r"(.+?),(https?://.+)", line):
            streams.append({
                "program_name": match.group(1).strip(),
                "stream_url": match.group(2).strip(),
                "meta": ""
            })
    return streams

def check_source_quality(url):
    """检测源响应速度和质量"""
    try:
        start = time.time()
        with requests.get(url, timeout=REQUEST_TIMEOUT, stream=True) as r:
            if r.status_code == 200:
                speed = time.time() - start
                return {"url": url, "speed": speed, "valid": True}
    except:
        pass
    return {"url": url, "speed": 999, "valid": False}

def filter_sources(sources):
    """过滤并排序源"""
    with ThreadPoolExecutor(THREAD_POOL) as executor:
        results = list(executor.map(check_source_quality, sources))
    
    valid_sources = sorted(
        [r for r in results if r["valid"]],
        key=lambda x: x["speed"]
    )
    return [s["url"] for s in valid_sources[:MAX_SOURCES_PER_CHANNEL]]

def organize_streams(content):
    # 解析内容（增强容错）
    try:
        parser = parse_m3u if content.startswith("#EXTM3U") else parse_txt
        streams = parser(content)
        df = pd.DataFrame(streams)
    except Exception as e:
        print(f"⚠️ 数据解析失败: {str(e)}")
        return pd.DataFrame()

    # 空数据防御
    if df.empty or "program_name" not in df.columns:
        print("⚠️ 输入数据无效或格式错误")
        return pd.DataFrame()

    # 过滤频道（增强正则容错）
    try:
        df = df[df["program_name"].str.contains(channel_pattern, na=False, regex=True)]
    except Exception as e:
        print(f"⚠️ 频道过滤失败: {str(e)}")
        df = df[df["program_name"].notna()]

    # 分组处理（终极正确写法）
    grouped = (
        df
        # 显式保留分组列
        [["program_name", "stream_url", "meta"]]  
        .groupby("program_name", group_keys=False)
        .apply(lambda x: (
            x
            .drop_duplicates(subset="stream_url")
            .head(100)
        ))
        # 重建完整数据结构
        .reset_index(drop=True)
    )

    # 结果校验
    if "program_name" not in grouped.columns:
        print("⚠️ 分组操作导致列丢失，启用紧急恢复模式")
        return df.drop_duplicates(["program_name", "stream_url"]).head(100)
    
    # 分组筛选最佳源
    filtered = []
    for name, group in grouped.groupby("program_name"):
        print(f"🔍 正在检测频道: {name}")
        best_sources = filter_sources(group["stream_url"].tolist())
        filtered.extend([
            {"program_name": name, "stream_url": url, "meta": group.iloc[0]["meta"]}
            for url in best_sources
        ])
    
    return pd.DataFrame(filtered)


def save_m3u(dataframe, filename="live.m3u"):
    filepath = os.path.abspath(filename)
    print(f"💾 正在保存文件到: {filepath}")
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("#EXTM3U x-tvg-url=\"\"\n")
        
        for _, row in dataframe.iterrows():
            # 生成分组信息
            protocol = "IPv6" if ipv6_pattern.match(row["stream_url"]) else "IPv4"
            
            # 写入频道信息
            extinf = row["meta"] or f'#EXTINF:-1 tvg-name="{row["program_name"]}" group-title="{protocol}",{row["program_name"]}'
            f.write(f"{extinf}\n{row["stream_url"]}\n")
    
    print(f"✅ 保存完成！有效频道数：{dataframe['program_name'].nunique()}")

if __name__ == "__main__":
    print("🚀 开始抓取直播源...")
    content = fetch_all_streams()
    
    if content:
        print("🔄 正在整理频道...")
        organized = organize_streams(content)
        
        if not organized.empty:
            print("🎉 有效源整理完成")
            save_m3u(organized)
        else:
            print("⚠️ 未找到符合要求的频道")
    else:
        print("❌ 未能获取有效内容")
