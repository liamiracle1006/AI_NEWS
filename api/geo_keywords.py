"""Country/region → keyword mapping for RSS article geo-tagging.

Keys are English country names that match Natural Earth 110m TopoJSON
`properties.NAME` values. Values are keyword lists (case-insensitive match
against article title + summary).

Political sensitivity notes:
- Taiwan keywords map to "China" so Taiwan-related articles boost China heat.
- Gaza/Palestine keywords map to "Palestine" which is rendered on the map
  as part of the surrounding area (no separate TopoJSON polygon at 110m).
- Tibet/Xinjiang keywords map to "China".
"""

GEO_KEYWORDS: dict[str, list[str]] = {
    # ── East Asia ──────────────────────────────────────────────────────────
    "China": [
        "China", "Chinese", "中国", "Beijing", "北京", "Shanghai", "上海",
        "Xi Jinping", "习近平", "PRC", "CCP", "中共",
        # Tibet / Xinjiang → China
        "Tibet", "西藏", "Xinjiang", "新疆", "Uyghur", "维吾尔",
        "Hong Kong", "香港",
    ],
    # Taiwan is tracked separately so clicks open a Taiwan-specific article list.
    # Display name on the map is "中国台湾" (handled in frontend ZH_NAMES).
    "Taiwan": [
        "Taiwan", "台湾", "Taipei", "台北", "TSMC", "台积电",
        "Lai Ching-te", "赖清德", "DPP", "民进党",
    ],
    "Japan": [
        "Japan", "Japanese", "日本", "Tokyo", "东京", "Osaka", "大阪",
        "Kishida", "岸田", "Abe", "安倍",
    ],
    "South Korea": [
        "South Korea", "Korean", "韩国", "Seoul", "首尔", "Yoon", "尹锡悦",
    ],
    "North Korea": [
        "North Korea", "DPRK", "朝鲜", "Pyongyang", "平壤", "Kim Jong Un",
        "金正恩",
    ],

    # ── Southeast Asia ─────────────────────────────────────────────────────
    "Vietnam": ["Vietnam", "Vietnamese", "越南", "Hanoi", "河内"],
    "Philippines": ["Philippines", "Filipino", "菲律宾", "Manila", "马尼拉", "Marcos"],
    "Myanmar": ["Myanmar", "Burma", "缅甸", "Yangon", "仰光"],
    "Thailand": ["Thailand", "Thai", "泰国", "Bangkok", "曼谷"],
    "Indonesia": ["Indonesia", "Indonesian", "印度尼西亚", "Jakarta", "雅加达"],
    "Malaysia": [
        "Malaysia", "Malaysian", "马来西亚", "Kuala Lumpur", "吉隆坡",
        # Singapore is too small for 110m map; its heat routes to Malaysia
        "Singapore", "新加坡",
    ],

    # ── South Asia ─────────────────────────────────────────────────────────
    "India": [
        "India", "Indian", "印度", "New Delhi", "新德里", "Modi", "莫迪",
        "BJP", "Mumbai", "孟买",
    ],
    "Pakistan": ["Pakistan", "Pakistani", "巴基斯坦", "Islamabad", "伊斯兰堡"],
    "Afghanistan": ["Afghanistan", "Afghan", "阿富汗", "Kabul", "喀布尔", "Taliban", "塔利班"],
    "Bangladesh": ["Bangladesh", "Bangladeshi", "孟加拉国", "Dhaka", "达卡"],

    # ── Central Asia ───────────────────────────────────────────────────────
    "Kazakhstan": ["Kazakhstan", "Kazakh", "哈萨克斯坦", "Astana", "阿斯塔纳"],
    "Iran": [
        "Iran", "Iranian", "伊朗", "Tehran", "德黑兰", "Khamenei",
        "哈梅内伊", "IRGC", "Revolutionary Guard",
    ],

    # ── Middle East ────────────────────────────────────────────────────────
    "Israel": [
        "Israel", "Israeli", "以色列", "Tel Aviv", "特拉维夫",
        "Jerusalem", "耶路撒冷", "Netanyahu", "内塔尼亚胡", "IDF",
        "Mossad", "Shin Bet",
    ],
    "Palestine": [
        "Gaza", "加沙", "Hamas", "哈马斯", "Palestinian", "巴勒斯坦",
        "West Bank", "约旦河西岸", "Rafah", "拉法", "Hezbollah", "真主党",
    ],
    "Lebanon": ["Lebanon", "Lebanese", "黎巴嫩", "Beirut", "贝鲁特"],
    "Syria": ["Syria", "Syrian", "叙利亚", "Damascus", "大马士革"],
    "Iraq": ["Iraq", "Iraqi", "伊拉克", "Baghdad", "巴格达"],
    "Saudi Arabia": [
        "Saudi Arabia", "Saudi", "沙特", "沙特阿拉伯", "Riyadh", "利雅得",
        "MBS", "Mohammed bin Salman", "穆罕默德·本·萨勒曼",
    ],
    "Yemen": ["Yemen", "Yemeni", "也门", "Houthi", "胡塞"],
    "Turkey": [
        "Turkey", "Turkish", "土耳其", "Ankara", "安卡拉", "Istanbul",
        "伊斯坦布尔", "Erdogan", "埃尔多安",
    ],
    "United Arab Emirates": ["UAE", "United Arab Emirates", "阿联酋", "Dubai", "迪拜", "Abu Dhabi"],
    "Qatar": ["Qatar", "卡塔尔", "Doha", "多哈"],
    "Jordan": ["Jordan", "Jordanian", "约旦", "Amman", "安曼"],
    "Egypt": ["Egypt", "Egyptian", "埃及", "Cairo", "开罗", "Sisi", "塞西"],
    "Libya": ["Libya", "Libyan", "利比亚", "Tripoli", "的黎波里"],

    # ── Europe ─────────────────────────────────────────────────────────────
    "Ukraine": [
        "Ukraine", "Ukrainian", "乌克兰", "Kyiv", "基辅", "Kiev",
        "Zelensky", "泽连斯基", "Donbas", "顿巴斯", "Kharkiv", "哈尔科夫",
        "Zaporizhzhia", "扎波罗热",
    ],
    "Russia": [
        "Russia", "Russian", "俄罗斯", "Moscow", "莫斯科", "Putin", "普京",
        "Kremlin", "克里姆林宫", "FSB", "SVR", "Lavrov", "拉夫罗夫",
        "Medvedev", "梅德韦杰夫",
    ],
    "Belarus": ["Belarus", "Belarusian", "白俄罗斯", "Minsk", "明斯克", "Lukashenko", "卢卡申科"],
    "Germany": ["Germany", "German", "德国", "Berlin", "柏林", "Scholz", "朔尔茨", "Merkel"],
    "France": [
        "France", "French", "法国", "Paris", "巴黎", "Macron", "马克龙",
        "Élysée",
    ],
    "United Kingdom": [
        "United Kingdom", "Britain", "British", "UK", "英国", "London",
        "伦敦", "Sunak", "苏纳克", "Starmer", "施凯尔",
    ],
    "Poland": ["Poland", "Polish", "波兰", "Warsaw", "华沙", "Tusk", "图斯克"],
    "Italy": ["Italy", "Italian", "意大利", "Rome", "罗马", "Meloni", "梅洛尼"],
    "Spain": ["Spain", "Spanish", "西班牙", "Madrid", "马德里"],
    "Sweden": ["Sweden", "Swedish", "瑞典", "Stockholm", "斯德哥尔摩"],
    "Finland": ["Finland", "Finnish", "芬兰", "Helsinki", "赫尔辛基"],
    "Romania": ["Romania", "Romanian", "罗马尼亚", "Bucharest", "布加勒斯特"],
    "Serbia": ["Serbia", "Serbian", "塞尔维亚", "Belgrade", "贝尔格莱德"],
    "Hungary": ["Hungary", "Hungarian", "匈牙利", "Budapest", "布达佩斯", "Orbán", "欧尔班"],
    "Georgia": ["Georgia", "Georgian", "格鲁吉亚", "Tbilisi", "第比利斯"],
    "Armenia": ["Armenia", "Armenian", "亚美尼亚", "Yerevan", "埃里温"],
    "Azerbaijan": ["Azerbaijan", "Azerbaijani", "阿塞拜疆", "Baku", "巴库"],
    "Netherlands": ["Netherlands", "Dutch", "荷兰", "Amsterdam", "阿姆斯特丹", "The Hague"],
    "Switzerland": ["Switzerland", "Swiss", "瑞士", "Geneva", "日内瓦", "Bern"],

    # ── Africa ─────────────────────────────────────────────────────────────
    "Sudan": ["Sudan", "Sudanese", "苏丹", "Khartoum", "喀土穆", "RSF", "Darfur", "达尔富尔"],
    "Ethiopia": ["Ethiopia", "Ethiopian", "埃塞俄比亚", "Addis Ababa", "亚的斯亚贝巴", "Tigray"],
    "Somalia": ["Somalia", "Somali", "索马里", "Mogadishu", "摩加迪沙", "al-Shabaab"],
    "Nigeria": ["Nigeria", "Nigerian", "尼日利亚", "Abuja", "阿布贾", "Lagos"],
    "South Africa": ["South Africa", "南非", "Johannesburg", "约翰内斯堡", "Pretoria", "比勒陀利亚"],
    "Kenya": ["Kenya", "Kenyan", "肯尼亚", "Nairobi", "内罗毕"],
    "Dem. Rep. Congo": [
        "Congo", "DRC", "刚果", "Kinshasa", "金沙萨",
    ],
    "Mali": ["Mali", "马里", "Bamako", "巴马科"],
    "Niger": ["Niger", "尼日尔", "Niamey", "尼亚美"],

    # ── Americas ───────────────────────────────────────────────────────────
    "United States of America": [
        "United States", "American", "美国", "Washington", "华盛顿",
        "Biden", "拜登", "Trump", "特朗普", "Pentagon", "五角大楼",
        "Congress", "Senate", "White House", "白宫", "CIA", "FBI",
        "New York", "纽约", "California", "加利福尼亚",
    ],
    "Canada": ["Canada", "Canadian", "加拿大", "Ottawa", "渥太华", "Trudeau", "特鲁多"],
    "Mexico": ["Mexico", "Mexican", "墨西哥", "Mexico City", "墨西哥城"],
    "Brazil": ["Brazil", "Brazilian", "巴西", "Brasília", "巴西利亚", "Lula", "卢拉"],
    "Argentina": ["Argentina", "Argentine", "阿根廷", "Buenos Aires", "布宜诺斯艾利斯", "Milei"],
    "Venezuela": ["Venezuela", "Venezuelan", "委内瑞拉", "Caracas", "加拉加斯", "Maduro", "马杜罗"],
    "Cuba": ["Cuba", "Cuban", "古巴", "Havana", "哈瓦那"],
    "Colombia": ["Colombia", "Colombian", "哥伦比亚", "Bogotá", "波哥大"],
    "Chile": ["Chile", "Chilean", "智利", "Santiago", "圣地亚哥"],

    # ── Oceania ────────────────────────────────────────────────────────────
    "Australia": [
        "Australia", "Australian", "澳大利亚", "Canberra", "堪培拉",
        "Sydney", "悉尼", "Albanese", "阿尔巴内塞",
    ],
    "New Zealand": ["New Zealand", "新西兰", "Wellington", "惠灵顿"],
}
