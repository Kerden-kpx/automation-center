import requests

payload = { 
    'api_key': '637aa3f197660ccfff635308c05e802e', 
    'url': 'https://www.amazon.com/Japanese-Reciprocating-Pruning-Storage-Trimming/dp/B0FZRPNKPB/',
    'render': 'true',
    # 'premium': 'true',
    'country_code': 'us'
}
r = requests.get('https://api.scraperapi.com/', params=payload)

with open("D:\\Yida_project\\automation-center\\scripts\\result.html", "w", encoding="utf-8") as f:
    f.write(r.text)

print(f"请求完成！状态码: {r.status_code}")
