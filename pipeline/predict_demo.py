"""pipeline/predict_demo.py

Demo proactive "rumour prediction" payloads.

This module intentionally contains deterministic, hardcoded scenarios to support
UI demos without requiring external services.

The SSE contract is implemented in app.py; this module only returns structured data.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DemoSource:
    label: str
    url: str


@dataclass(frozen=True)
class DemoHistoricalPattern:
    event: str
    similarity: int
    note: str
    source: str | None = None


def _covid_dorscon() -> dict:
    topics = {
        "topics": [
            "DORSCON Orange",
            "Supermarket supply chains",
            "Panic buying",
            "Public health advisories",
            "Rumour propagation on WhatsApp",
        ],
        "affectedCommunities": [
            "Mandarin-dominant elderly",
            "Heartland households",
            "Parents of young children",
            "Migrant worker dormitories",
        ],
        "emotionalTriggers": [
            "Scarcity anxiety",
            "Fear of lockdown",
            "Institutional distrust",
            "Health fear",
        ],
    }

    sources: list[DemoSource] = [
        DemoSource("MOH — DORSCON framework", "https://www.moh.gov.sg"),
        DemoSource("gov.sg — Official updates", "https://www.gov.sg"),
        DemoSource("CNA — Panic buying coverage", "https://www.channelnewsasia.com"),
        DemoSource("POFMA Office — Corrections", "https://www.pofmaoffice.gov.sg"),
    ]

    predictions = [
        {
            "id": "rice-shortage",
            "risk": "HIGH",
            "risk_score": 92,
            "title": "Sheng Siong and NTUC FairPrice have run out of rice. All rice stocks in Singapore are finished.",
            "channel": "WhatsApp groups (Mandarin), Facebook community pages",
            "trigger": "Survival anxiety",
            "demographic_risk": "Mandarin-speaking elderly, heartland residents",
            "time_to_spread": "Estimated 2–4 hours",
            "historical_match": "Matches panic-buying patterns from 2003 SARS outbreak. Essentials become hoarding targets early.",
            "historical_similarity": 88,
            "counter_narratives": {
                "en": (
                    "This is not true. Singapore's rice supply remains stable. The government maintains national stockpiles "
                    "of essential items including rice, and supply chains are operating normally. Major supermarkets have "
                    "confirmed continuous restocking. Please buy only what you need."
                ),
                "zh": (
                    "这不是事实。新加坡的大米供应保持稳定。政府维持包括大米在内的必需品国家储备，供应链运作正常。"
                    "各大超市已确认会持续补货。请只购买所需，不必恐慌抢购。"
                ),
                "ms": (
                    "Ini tidak benar. Bekalan beras Singapura kekal stabil. Kerajaan mengekalkan stok simpanan negara "
                    "dan rantaian bekalan beroperasi seperti biasa. Pasar raya utama mengesahkan mereka terus mengisi semula rak."
                ),
                "ta": (
                    "இது உண்மையல்ல. சிங்கப்பூரின் அரிசி விநியோகம் நிலையாக உள்ளது. அரசாங்கம் தேசிய இருப்புகளை பராமரிக்கிறது, "
                    "மேலும் விநியோகச் சங்கிலிகள் இயல்பாகச் செயல்படுகின்றன. முக்கிய சூப்பர்மார்க்கெட்டுகள் தொடர்ந்து அலமாரிகளை நிரப்புகின்றன."
                ),
            },
            "sources": [
                {"label": "MOH", "url": "https://www.moh.gov.sg"},
                {"label": "gov.sg", "url": "https://www.gov.sg"},
            ],
            "policy_recommendations": [
                "Publish a short, shareable supply-chain reassurance paragraph.",
                "Pre-brief supermarkets and prepare a unified restocking statement.",
            ],
        },
        {
            "id": "toilet-paper",
            "risk": "HIGH",
            "risk_score": 87,
            "title": "Toilet paper and household essentials will be unavailable for weeks. Singapore imports are being cut off.",
            "channel": "Cross-language WhatsApp, Telegram groups, Facebook",
            "trigger": "Scarcity anxiety",
            "demographic_risk": "General population, especially heartland households",
            "time_to_spread": "Estimated 3–6 hours",
            "historical_match": "Toilet paper panic is a common crisis response globally and spreads quickly through forwarded messages.",
            "historical_similarity": 82,
            "counter_narratives": {
                "en": (
                    "Singapore's supply of household essentials remains fully stocked. Singapore imports from multiple sources "
                    "and maintains buffer stocks. Panic-buying creates artificial shortages — please buy only what you need."
                ),
                "zh": (
                    "新加坡的日用品供应充足，包括卫生纸在内。我们从多个国家进口并维持缓冲库存。恐慌抢购只会造成暂时性短缺。"
                    "请只购买所需。"
                ),
                "ms": (
                    "Bekalan barangan keperluan harian termasuk kertas tandas kekal mencukupi. Singapura mengimport dari pelbagai negara "
                    "dan mengekalkan stok penampan. Pembelian panik hanya mewujudkan kekurangan sementara."
                ),
                "ta": (
                    "கழிவறைத் தாள் உள்ளிட்ட வீட்டு அத்தியாவசியப் பொருட்களின் விநியோகம் போதுமானதாக உள்ளது. சிங்கப்பூர் பல நாடுகளிலிருந்து இறக்குமதி செய்கிறது "
                    "மற்றும் இடையக இருப்புகளை பராமரிக்கிறது. பீதி கொள்முதல் தற்காலிக பற்றாக்குறையை உருவாக்கும்."
                ),
            },
            "sources": [
                {"label": "CNA", "url": "https://www.channelnewsasia.com"},
                {"label": "gov.sg", "url": "https://www.gov.sg"},
            ],
            "policy_recommendations": [
                "Release a one-slide graphic on supply continuity for sharing.",
                "Coordinate a single daily update on essential goods availability.",
            ],
        },
        {
            "id": "cover-up",
            "risk": "MEDIUM",
            "risk_score": 68,
            "title": "The government is hiding the real number of cases. DORSCON Orange means a lockdown is coming and they're not telling us.",
            "channel": "Twitter/X, Reddit r/singapore, Telegram",
            "trigger": "Institutional distrust",
            "demographic_risk": "English-speaking online-first users",
            "time_to_spread": "Estimated 4–8 hours",
            "historical_match": "Transparency rumours recur whenever public health measures escalate; they amplify uncertainty.",
            "historical_similarity": 71,
            "counter_narratives": {
                "en": (
                    "DORSCON Orange is a transparent, pre-established national framework — not a sign of hidden information. "
                    "Confirmed case counts are published via official MOH updates. Orange means precautionary measures are being activated."
                ),
                "zh": (
                    "DORSCON橙色是透明且预先建立的国家框架，并非隐瞒信息的信号。卫生部会发布官方病例更新。橙色表示启动预防措施。"
                ),
                "ms": (
                    "Tahap DORSCON Oren ialah rangka kerja kebangsaan yang telus — bukan tanda maklumat disembunyikan. "
                    "MOH menerbitkan kemas kini rasmi kes. Oren bermaksud langkah berjaga-jaga sedang diaktifkan."
                ),
                "ta": (
                    "DORSCON ஆரஞ்சு என்பது வெளிப்படையான தேசிய கட்டமைப்பு — மறைக்கப்பட்ட தகவலின் அறிகுறி அல்ல. "
                    "MOH அதிகாரப்பூர்வ புதுப்பிப்புகளில் உறுதிப்படுத்தப்பட்ட எண்ணிக்கைகள் வெளியிடப்படுகின்றன. ஆரஞ்சு என்பது முன்னெச்சரிக்கை நடவடிக்கைகள் செயல்படுவது."
                ),
            },
            "sources": [
                {"label": "MOH", "url": "https://www.moh.gov.sg"},
            ],
            "policy_recommendations": [
                "Publish a simple explainer: what each DORSCON level means.",
                "Link to the daily case-update page in the advisory footer.",
            ],
        },
    ]

    historical_patterns = [
        {
            "event": "SARS (2003) — essentials hoarding",
            "similarity": 88,
            "note": "Early rumours targeted household staples; WhatsApp-like forwarding dynamics appear in later crises.",
        },
        {
            "event": "H1N1 (2009) — transparency concerns",
            "similarity": 71,
            "note": "Escalation in measures often triggers speculation about hidden information.",
        },
    ]

    return {
        "topics": topics,
        "sources": [s.__dict__ for s in sources],
        "predictions": predictions,
        "historicalPatterns": historical_patterns,
        "communityLeadersCount": 847,
        "constituencies": [
            "Tampines",
            "Ang Mo Kio",
            "Jurong",
            "Woodlands",
            "Bedok",
        ],
    }


def _nipah() -> dict:
    topics = {
        "topics": [
            "Nipah virus",
            "Zoonotic surveillance",
            "Food safety",
            "Dormitory health measures",
            "Public health communications",
        ],
        "affectedCommunities": [
            "Parents of young children",
            "Migrant workers in dormitories",
            "Mandarin-dominant elderly",
            "Malay-speaking communities",
        ],
        "emotionalTriggers": [
            "Fear of cover-up",
            "Xenophobia & scapegoating",
            "Food safety panic",
        ],
    }

    sources: list[DemoSource] = [
        DemoSource("WHO — Nipah virus facts", "https://www.who.int"),
        DemoSource("MOH — Communicable diseases", "https://www.moh.gov.sg"),
        DemoSource("CNA — Health reporting", "https://www.channelnewsasia.com"),
    ]

    predictions = [
        {
            "id": "fruit-ban",
            "risk": "MEDIUM",
            "risk_score": 74,
            "title": "All imported fruit is contaminated. You must stop eating fruit immediately.",
            "channel": "WhatsApp forwards, Facebook",
            "trigger": "Food safety panic",
            "demographic_risk": "Families and elderly concerned about diet safety",
            "time_to_spread": "Estimated 3–6 hours",
            "historical_match": "Food contamination rumours spread quickly during outbreaks and often distort official advisories.",
            "historical_similarity": 66,
            "counter_narratives": {
                "en": "Do not rely on forwarded messages. Follow MOH/WHO advisories. If any product recalls are needed, they will be announced officially.",
                "zh": "不要依赖转发消息。请以卫生部/世卫组织的官方通告为准。如需召回产品，将会有正式公告。",
                "ms": "Jangan bergantung pada mesej yang diteruskan. Ikuti nasihat rasmi MOH/WHO. Jika ada penarikan balik produk, ia akan diumumkan secara rasmi.",
                "ta": "முன்னேற்றப்பட்ட செய்திகளை நம்ப வேண்டாம். MOH/WHO அதிகாரப்பூர்வ அறிவுறுத்தல்களை பின்பற்றவும். தேவையானால் தயாரிப்பு மீட்பு அதிகாரப்பூர்வமாக அறிவிக்கப்படும்.",
            },
            "sources": [
                {"label": "WHO", "url": "https://www.who.int"},
            ],
            "policy_recommendations": [
                "Add a clear food-safety FAQ section with shareable links.",
            ],
        }
    ]

    historical_patterns = [
        {
            "event": "Zika (2016) — mosquito rumours",
            "similarity": 62,
            "note": "Health outbreaks frequently produce exaggerated household guidance rumours.",
        }
    ]

    return {
        "topics": topics,
        "sources": [s.__dict__ for s in sources],
        "predictions": predictions,
        "historicalPatterns": historical_patterns,
        "communityLeadersCount": 512,
        "constituencies": [
            "Geylang",
            "Sengkang",
            "Yishun",
        ],
    }


def get_demo_prediction(text: str) -> dict:
    """Return a demo prediction payload for the given announcement text."""
    lowered = (text or "").lower()
    if "nipah" in lowered:
        return _nipah()
    return _covid_dorscon()
