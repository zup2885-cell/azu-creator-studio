"""Validate an editable reading summary without replacing the full evidence."""


def validate_brief(value,item_ids):
    def short(raw,limit,label):
        if not isinstance(raw,str) or not raw.strip() or len(raw.strip())>limit:
            raise ValueError(f'报告简读的{label}需为1–{limit}字')
        return raw.strip()
    if not isinstance(value,dict):raise ValueError('报告缺少有效简读内容')
    conclusion=short(value.get('conclusion'),60,'建议')
    caveat=short(value.get('caveat'),70,'注意事项')
    points=value.get('points');actions=value.get('actions')
    if not isinstance(points,list) or not 1<=len(points)<=3:raise ValueError('报告简读需有1–3条重点')
    if not isinstance(actions,list) or not 1<=len(actions)<=3:raise ValueError('报告简读需有1–3条具体行动')
    clean=[]
    for row in points:
        if not isinstance(row,dict):raise ValueError('报告简读重点格式无效')
        ids=row.get('item_ids')
        if not isinstance(ids,list) or not ids or len(ids)>12 or any(not isinstance(i,str) or i not in item_ids for i in ids):
            raise ValueError('报告简读重点必须引用本次素材')
        clean.append({'title':short(row.get('title'),14,'重点标题'),'detail':short(row.get('detail'),54,'重点说明'),'item_ids':list(dict.fromkeys(ids))})
    result={'conclusion':conclusion,'points':clean,'actions':[short(v,48,'行动建议') for v in actions],'caveat':caveat}
    size=len(conclusion)+len(caveat)+sum(len(r['title'])+len(r['detail']) for r in clean)+sum(map(len,result['actions']))
    if size>420:raise ValueError('报告简读合计不能超过420字')
    return result
