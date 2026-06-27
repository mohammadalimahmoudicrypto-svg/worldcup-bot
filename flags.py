_FLAGS = {
    # South America
    "Argentina": "🇦🇷", "Brazil": "🇧🇷", "Colombia": "🇨🇴", "Uruguay": "🇺🇾",
    "Ecuador": "🇪🇨", "Paraguay": "🇵🇾", "Venezuela": "🇻🇪", "Bolivia": "🇧🇴",
    "Peru": "🇵🇪", "Chile": "🇨🇱",
    # CONCACAF
    "United States": "🇺🇸", "USA": "🇺🇸", "Mexico": "🇲🇽", "Canada": "🇨🇦",
    "Panama": "🇵🇦", "Honduras": "🇭🇳", "Jamaica": "🇯🇲", "Costa Rica": "🇨🇷",
    "Cuba": "🇨🇺", "Trinidad and Tobago": "🇹🇹", "Guatemala": "🇬🇹",
    "El Salvador": "🇸🇻", "Haiti": "🇭🇹",
    # Europe
    "Germany": "🇩🇪", "Spain": "🇪🇸", "France": "🇫🇷", "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "Portugal": "🇵🇹", "Netherlands": "🇳🇱", "Belgium": "🇧🇪", "Italy": "🇮🇹",
    "Croatia": "🇭🇷", "Denmark": "🇩🇰", "Serbia": "🇷🇸", "Austria": "🇦🇹",
    "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "Wales": "🏴󠁧󠁢󠁷󠁬󠁳󠁿", "Turkey": "🇹🇷", "Türkiye": "🇹🇷",
    "Hungary": "🇭🇺", "Czech Republic": "🇨🇿", "Czechia": "🇨🇿", "Slovakia": "🇸🇰",
    "Slovenia": "🇸🇮", "Albania": "🇦🇱", "Romania": "🇷🇴", "Georgia": "🇬🇪",
    "Switzerland": "🇨🇭", "Poland": "🇵🇱", "Ukraine": "🇺🇦", "Greece": "🇬🇷",
    "Sweden": "🇸🇪", "Norway": "🇳🇴", "Finland": "🇫🇮", "Iceland": "🇮🇸",
    "Ireland": "🇮🇪", "Republic of Ireland": "🇮🇪", "Northern Ireland": "🇬🇧",
    "Luxembourg": "🇱🇺", "Bosnia and Herzegovina": "🇧🇦", "Montenegro": "🇲🇪",
    "North Macedonia": "🇲🇰", "Cyprus": "🇨🇾", "Israel": "🇮🇱", "Kosovo": "🇽🇰",
    "Armenia": "🇦🇲", "Azerbaijan": "🇦🇿", "Belarus": "🇧🇾", "Estonia": "🇪🇪",
    "Latvia": "🇱🇻", "Lithuania": "🇱🇹", "Moldova": "🇲🇩", "Kazakhstan": "🇰🇿",
    "Russia": "🇷🇺",
    # Asia
    "Japan": "🇯🇵", "South Korea": "🇰🇷", "Korea Republic": "🇰🇷", "Australia": "🇦🇺",
    "Iran": "🇮🇷", "Saudi Arabia": "🇸🇦", "Qatar": "🇶🇦", "Uzbekistan": "🇺🇿",
    "Iraq": "🇮🇶", "Jordan": "🇯🇴", "China": "🇨🇳", "China PR": "🇨🇳",
    "Indonesia": "🇮🇩", "Bahrain": "🇧🇭", "North Korea": "🇰🇵", "Korea DPR": "🇰🇵",
    "Kyrgyzstan": "🇰🇬", "Kuwait": "🇰🇼", "UAE": "🇦🇪", "United Arab Emirates": "🇦🇪",
    "Thailand": "🇹🇭", "Vietnam": "🇻🇳", "Malaysia": "🇲🇾", "Philippines": "🇵🇭",
    "India": "🇮🇳", "Syria": "🇸🇾", "Palestine": "🇵🇸", "Oman": "🇴🇲",
    "Tajikistan": "🇹🇯", "Myanmar": "🇲🇲", "Lebanon": "🇱🇧",
    # Africa
    "Morocco": "🇲🇦", "Senegal": "🇸🇳", "Nigeria": "🇳🇬", "Egypt": "🇪🇬",
    "Cameroon": "🇨🇲", "Ivory Coast": "🇨🇮", "Côte d'Ivoire": "🇨🇮", "Mali": "🇲🇱",
    "South Africa": "🇿🇦", "Tanzania": "🇹🇿", "Congo DR": "🇨🇩", "DR Congo": "🇨🇩",
    "Tunisia": "🇹🇳", "Algeria": "🇩🇿", "Ghana": "🇬🇭", "Mozambique": "🇲🇿",
    "Zambia": "🇿🇲", "Uganda": "🇺🇬", "Kenya": "🇰🇪", "Ethiopia": "🇪🇹",
    "Angola": "🇦🇴", "Cape Verde": "🇨🇻", "Guinea": "🇬🇳", "Burkina Faso": "🇧🇫",
    "Sudan": "🇸🇩", "Libya": "🇱🇾", "Rwanda": "🇷🇼", "Comoros": "🇰🇲",
    "Namibia": "🇳🇦", "Mauritania": "🇲🇷", "Niger": "🇳🇪",
    # Oceania
    "New Zealand": "🇳🇿", "Fiji": "🇫🇯", "Papua New Guinea": "🇵🇬",
    "Solomon Islands": "🇸🇧", "Vanuatu": "🇻🇺",
}


def flag(team_name: str) -> str:
    return _FLAGS.get(team_name, "")
