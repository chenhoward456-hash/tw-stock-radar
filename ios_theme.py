"""
iOS Native Theme for Streamlit
Transforms the Streamlit dashboard into an iPhone-native look & feel.

Usage in app.py:
    import ios_theme
    ios_theme.apply()

Helper components:
    ios_theme.score_card("技術面", 8.5, "green")
    ios_theme.signal_badge("green", "多頭確認")
    ios_theme.metric_ring(7.2, 10, "綜合評分")
    ios_theme.section_header("今日焦點", "打開就知道今天該關注什麼")
"""
import streamlit as st

# ---------------------------------------------------------------------------
# iOS Design Tokens
# ---------------------------------------------------------------------------
IOS_COLORS = {
    "blue": "#007AFF",
    "green": "#34C759",
    "red": "#FF3B30",
    "yellow": "#FF9500",
    "teal": "#5AC8FA",
    "purple": "#AF52DE",
    "pink": "#FF2D55",
    "gray": "#8E8E93",
    "gray2": "#AEAEB2",
    "gray3": "#C7C7CC",
    "gray4": "#D1D1D6",
    "gray5": "#E5E5EA",
    "gray6": "#F2F2F7",
    "label": "#000000",
    "secondaryLabel": "#3C3C43",
    "tertiaryLabel": "#48484A",
    "bg": "#F2F2F7",
    "card": "#FFFFFF",
    "separator": "#C6C6C8",
}

# ---------------------------------------------------------------------------
# Main CSS
# ---------------------------------------------------------------------------
IOS_CSS = """
<style>
/* ======================================================
   iOS NATIVE THEME FOR STREAMLIT
   San Francisco font stack, rounded cards, system colors
   ====================================================== */

/* ----- Font Stack (SF Pro approximation) ----- */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

:root {
    /* iOS System Colors — Light */
    --ios-blue: #007AFF;
    --ios-green: #34C759;
    --ios-red: #FF3B30;
    --ios-yellow: #FF9500;
    --ios-orange: #FF9500;
    --ios-teal: #5AC8FA;
    --ios-purple: #AF52DE;
    --ios-pink: #FF2D55;

    /* iOS Grays */
    --ios-gray: #8E8E93;
    --ios-gray2: #AEAEB2;
    --ios-gray3: #C7C7CC;
    --ios-gray4: #D1D1D6;
    --ios-gray5: #E5E5EA;
    --ios-gray6: #F2F2F7;

    /* Semantic */
    --ios-label: #000000;
    --ios-secondary-label: #3C3C43;
    --ios-tertiary-label: rgba(60, 60, 67, 0.6);
    --ios-quaternary-label: rgba(60, 60, 67, 0.18);
    --ios-bg: #F2F2F7;
    --ios-card-bg: #FFFFFF;
    --ios-separator: rgba(60, 60, 67, 0.12);
    --ios-grouped-bg: #F2F2F7;

    /* Spacing */
    --ios-radius: 12px;
    --ios-radius-lg: 16px;
    --ios-radius-sm: 8px;
    --ios-padding: 16px;
    --ios-padding-lg: 20px;

    /* Shadows */
    --ios-shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.06);
    --ios-shadow-md: 0 2px 8px rgba(0, 0, 0, 0.08);
    --ios-shadow-lg: 0 4px 16px rgba(0, 0, 0, 0.1);
    --ios-shadow-card: 0 1px 3px rgba(0, 0, 0, 0.04), 0 4px 12px rgba(0, 0, 0, 0.06);

    /* Typography */
    --ios-font: 'Inter', -apple-system, BlinkMacSystemFont, 'SF Pro Display',
        'SF Pro Text', 'Helvetica Neue', Arial, sans-serif;
    --ios-font-rounded: 'SF Pro Rounded', 'Inter', -apple-system, sans-serif;

    /* Transitions */
    --ios-transition: 0.2s cubic-bezier(0.25, 0.1, 0.25, 1);
}

/* ----- Dark Mode Tokens ----- */
@media (prefers-color-scheme: dark) {
    :root {
        --ios-blue: #0A84FF;
        --ios-green: #30D158;
        --ios-red: #FF453A;
        --ios-yellow: #FF9F0A;
        --ios-orange: #FF9F0A;
        --ios-teal: #64D2FF;
        --ios-purple: #BF5AF2;
        --ios-pink: #FF375F;

        --ios-gray: #8E8E93;
        --ios-gray2: #636366;
        --ios-gray3: #48484A;
        --ios-gray4: #3A3A3C;
        --ios-gray5: #2C2C2E;
        --ios-gray6: #1C1C1E;

        --ios-label: #FFFFFF;
        --ios-secondary-label: rgba(235, 235, 245, 0.6);
        --ios-tertiary-label: rgba(235, 235, 245, 0.3);
        --ios-quaternary-label: rgba(235, 235, 245, 0.08);
        --ios-bg: #000000;
        --ios-card-bg: #1C1C1E;
        --ios-separator: rgba(84, 84, 88, 0.65);
        --ios-grouped-bg: #000000;

        --ios-shadow-sm: none;
        --ios-shadow-md: none;
        --ios-shadow-lg: none;
        --ios-shadow-card: 0 0 0 0.5px rgba(255, 255, 255, 0.08);
    }
}

/* Streamlit dark mode override (data-theme attribute) */
[data-theme="dark"],
.stApp[data-theme="dark"],
[data-testid="stAppViewContainer"][data-theme="dark"] {
    --ios-blue: #0A84FF;
    --ios-green: #30D158;
    --ios-red: #FF453A;
    --ios-yellow: #FF9F0A;
    --ios-label: #FFFFFF;
    --ios-secondary-label: rgba(235, 235, 245, 0.6);
    --ios-tertiary-label: rgba(235, 235, 245, 0.3);
    --ios-bg: #000000;
    --ios-card-bg: #1C1C1E;
    --ios-separator: rgba(84, 84, 88, 0.65);
    --ios-shadow-card: 0 0 0 0.5px rgba(255, 255, 255, 0.08);
}


/* ==========================================================
   DARK MODE FIX — 強制白字，解決灰字看不清的問題
   ========================================================== */
@media (prefers-color-scheme: dark) {
    .stApp, .stApp * {
        color: #F5F5F7 !important;
    }
    .stApp h1, .stApp h2, .stApp h3, .stApp h4 {
        color: #FFFFFF !important;
    }
    .stApp p, .stApp span, .stApp label, .stApp div {
        color: #F5F5F7 !important;
    }
    .stApp .stCaption, [data-testid="stCaptionContainer"] {
        color: #AEAEB2 !important;
    }
    .stApp a {
        color: #0A84FF !important;
    }
}
[data-theme="dark"] .stApp,
[data-theme="dark"] .stApp * {
    color: #F5F5F7 !important;
}
[data-theme="dark"] .stApp h1,
[data-theme="dark"] .stApp h2,
[data-theme="dark"] .stApp h3 {
    color: #FFFFFF !important;
}
[data-theme="dark"] .stCaption,
[data-theme="dark"] [data-testid="stCaptionContainer"] {
    color: #AEAEB2 !important;
}

/* ==========================================================
   GLOBAL — Background & Typography
   ========================================================== */
.stApp,
[data-testid="stAppViewContainer"] {
    font-family: var(--ios-font) !important;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

/* Give the main content area an iOS grouped background */
[data-testid="stAppViewContainer"] > section > div {
    /* Do not override background if Streamlit handles dark mode */
}

.main .block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 4rem !important;
    max-width: 768px !important;
}

/* Mobile: tighter padding */
@media (max-width: 768px) {
    .main .block-container {
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        padding-top: 1rem !important;
    }
}


/* ==========================================================
   SIDEBAR — iOS Tab-Bar / Settings Style
   ========================================================== */
[data-testid="stSidebar"] {
    background-color: var(--ios-card-bg) !important;
    border-right: 0.5px solid var(--ios-separator) !important;
}

[data-testid="stSidebar"] > div:first-child {
    padding-top: 2rem;
}

/* Sidebar title */
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h1 {
    font-weight: 700 !important;
    font-size: 1.5rem !important;
    letter-spacing: -0.02em !important;
}

/* Sidebar radio = iOS list rows */
[data-testid="stSidebar"] .stRadio > div {
    gap: 0 !important;
}

[data-testid="stSidebar"] .stRadio > div > label {
    background: var(--ios-card-bg) !important;
    border: none !important;
    border-bottom: 0.5px solid var(--ios-separator) !important;
    border-radius: 0 !important;
    padding: 14px 16px !important;
    margin: 0 !important;
    font-size: 1rem !important;
    font-weight: 500 !important;
    transition: background var(--ios-transition) !important;
    cursor: pointer;
}

/* First and last items get rounded corners (iOS grouped list) */
[data-testid="stSidebar"] .stRadio > div > label:first-child {
    border-radius: var(--ios-radius) var(--ios-radius) 0 0 !important;
}

[data-testid="stSidebar"] .stRadio > div > label:last-child {
    border-radius: 0 0 var(--ios-radius) var(--ios-radius) !important;
    border-bottom: none !important;
}

[data-testid="stSidebar"] .stRadio > div > label:hover {
    background: var(--ios-gray6) !important;
}

/* Active radio item */
[data-testid="stSidebar"] .stRadio > div > label[data-checked="true"],
[data-testid="stSidebar"] .stRadio > div > label:has(input:checked) {
    background: rgba(0, 122, 255, 0.08) !important;
    color: var(--ios-blue) !important;
    font-weight: 600 !important;
}

/* Hide default radio circles */
[data-testid="stSidebar"] .stRadio > div > label > div:first-child {
    display: none !important;
}

/* Sidebar selectbox */
[data-testid="stSidebar"] [data-testid="stSelectbox"] {
    margin-top: 8px;
}


/* ==========================================================
   TITLES & HEADINGS
   ========================================================== */
h1, h2, h3, h4, h5, h6,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 {
    font-family: var(--ios-font) !important;
    letter-spacing: -0.02em !important;
    font-weight: 700 !important;
}

/* Page title — iOS large title */
.main h1,
[data-testid="stMarkdownContainer"] h1 {
    font-size: 2rem !important;
    font-weight: 800 !important;
    letter-spacing: -0.03em !important;
    margin-bottom: 0.25rem !important;
}

/* Section title */
.main h3,
[data-testid="stMarkdownContainer"] h3 {
    font-size: 1.25rem !important;
    font-weight: 700 !important;
    margin-top: 1.5rem !important;
    margin-bottom: 0.5rem !important;
}

/* Caption / secondary text */
[data-testid="stCaptionContainer"],
.stCaption {
    color: var(--ios-tertiary-label) !important;
    font-size: 0.8125rem !important;
    line-height: 1.4 !important;
}


/* ==========================================================
   BUTTONS — iOS Rounded Style
   ========================================================== */
.stButton > button,
.stFormSubmitButton > button {
    font-family: var(--ios-font) !important;
    font-weight: 600 !important;
    font-size: 1rem !important;
    border-radius: var(--ios-radius) !important;
    min-height: 50px !important;
    padding: 12px 24px !important;
    border: none !important;
    transition: all var(--ios-transition) !important;
    letter-spacing: -0.01em !important;
}

/* Primary button — iOS blue filled */
.stButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"],
button[data-testid="stBaseButton-primary"] {
    background-color: var(--ios-blue) !important;
    color: #FFFFFF !important;
    box-shadow: var(--ios-shadow-sm) !important;
}

button[data-testid="stBaseButton-primary"]:hover {
    background-color: #0071EB !important;
    transform: scale(0.98) !important;
    box-shadow: var(--ios-shadow-md) !important;
}

button[data-testid="stBaseButton-primary"]:active {
    transform: scale(0.96) !important;
    opacity: 0.85;
}

/* Secondary / default button */
.stButton > button[kind="secondary"],
.stButton > button:not([data-testid="stBaseButton-primary"]) {
    background-color: var(--ios-gray6) !important;
    color: var(--ios-blue) !important;
    border: none !important;
}

.stButton > button:not([data-testid="stBaseButton-primary"]):hover {
    background-color: var(--ios-gray5) !important;
    transform: scale(0.98) !important;
}

.stButton > button:not([data-testid="stBaseButton-primary"]):active {
    transform: scale(0.96) !important;
}


/* ==========================================================
   TEXT INPUT / NUMBER INPUT / SELECT — iOS Fields
   ========================================================== */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
.stTextInput input,
.stNumberInput input {
    font-family: var(--ios-font) !important;
    font-size: 1rem !important;
    border-radius: var(--ios-radius) !important;
    border: 1px solid var(--ios-gray4) !important;
    padding: 12px 14px !important;
    min-height: 48px !important;
    background: var(--ios-card-bg) !important;
    transition: border-color var(--ios-transition) !important;
}

[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
.stTextInput input:focus,
.stNumberInput input:focus {
    border-color: var(--ios-blue) !important;
    box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.15) !important;
    outline: none !important;
}

/* Selectbox */
[data-testid="stSelectbox"] > div > div {
    border-radius: var(--ios-radius) !important;
    border: 1px solid var(--ios-gray4) !important;
    min-height: 48px !important;
}

/* Labels */
.stTextInput label,
.stNumberInput label,
.stSelectbox label,
.stDateInput label {
    font-family: var(--ios-font) !important;
    font-weight: 600 !important;
    font-size: 0.875rem !important;
    color: var(--ios-secondary-label) !important;
    margin-bottom: 4px !important;
}


/* ==========================================================
   ALERT BOXES — iOS Rounded Cards with Signal Colors
   ========================================================== */
/* Base alert style */
[data-testid="stAlert"],
.stAlert,
div[data-testid="stNotification"] {
    border-radius: var(--ios-radius) !important;
    border: none !important;
    padding: 14px 16px !important;
    font-size: 0.9375rem !important;
    line-height: 1.5 !important;
    margin-bottom: 10px !important;
    box-shadow: var(--ios-shadow-sm) !important;
}

/* Success — green */
div[data-testid="stAlert"][data-baseweb*="positive"],
div[role="alert"]:has(> div > svg[data-testid="stIconMaterial"]) {
    /* Handled by Streamlit's own coloring; we just ensure radius/padding */
}

/* Override success background */
.element-container:has([data-baseweb*="positive"]) [data-testid="stAlert"],
[data-testid="stNotification"][data-type="success"] {
    background-color: rgba(52, 199, 89, 0.08) !important;
    border-left: 4px solid var(--ios-green) !important;
}

[data-testid="stNotification"][data-type="warning"] {
    background-color: rgba(255, 149, 0, 0.08) !important;
    border-left: 4px solid var(--ios-yellow) !important;
}

[data-testid="stNotification"][data-type="error"] {
    background-color: rgba(255, 59, 48, 0.08) !important;
    border-left: 4px solid var(--ios-red) !important;
}

[data-testid="stNotification"][data-type="info"] {
    background-color: rgba(0, 122, 255, 0.08) !important;
    border-left: 4px solid var(--ios-blue) !important;
}

/* Streamlit uses different selectors across versions — cover all */
.stSuccess {
    background-color: rgba(52, 199, 89, 0.08) !important;
    border-left: 4px solid var(--ios-green) !important;
    border-radius: var(--ios-radius) !important;
}

.stWarning {
    background-color: rgba(255, 149, 0, 0.08) !important;
    border-left: 4px solid var(--ios-yellow) !important;
    border-radius: var(--ios-radius) !important;
}

.stError {
    background-color: rgba(255, 59, 48, 0.08) !important;
    border-left: 4px solid var(--ios-red) !important;
    border-radius: var(--ios-radius) !important;
}

.stInfo {
    background-color: rgba(0, 122, 255, 0.08) !important;
    border-left: 4px solid var(--ios-blue) !important;
    border-radius: var(--ios-radius) !important;
}


/* ==========================================================
   METRICS — iOS Health App Inspired Large Numbers
   ========================================================== */
[data-testid="stMetric"],
[data-testid="metric-container"] {
    background: var(--ios-card-bg) !important;
    border-radius: var(--ios-radius) !important;
    padding: 16px 16px 14px !important;
    box-shadow: var(--ios-shadow-card) !important;
    border: 0.5px solid var(--ios-separator) !important;
    transition: transform var(--ios-transition) !important;
}

[data-testid="stMetric"]:hover,
[data-testid="metric-container"]:hover {
    transform: translateY(-1px) !important;
}

[data-testid="stMetricLabel"] {
    font-family: var(--ios-font) !important;
    font-size: 0.8125rem !important;
    font-weight: 600 !important;
    color: var(--ios-tertiary-label) !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
}

[data-testid="stMetricValue"] {
    font-family: var(--ios-font) !important;
    font-size: 2rem !important;
    font-weight: 800 !important;
    letter-spacing: -0.03em !important;
    color: var(--ios-label) !important;
    line-height: 1.2 !important;
}

[data-testid="stMetricDelta"] {
    font-family: var(--ios-font) !important;
    font-size: 0.875rem !important;
    font-weight: 600 !important;
}

/* Positive delta — green */
[data-testid="stMetricDelta"][style*="color: rgb(9, 171, 59)"],
[data-testid="stMetricDelta"] svg[style*="color: rgb(9, 171, 59)"] ~ span {
    color: var(--ios-green) !important;
}

/* Negative delta — red */
[data-testid="stMetricDelta"][style*="color: rgb(255, 43, 43)"],
[data-testid="stMetricDelta"] svg[style*="color: rgb(255, 43, 43)"] ~ span {
    color: var(--ios-red) !important;
}


/* ==========================================================
   DATAFRAMES & TABLES — Clean iOS Style
   ========================================================== */
[data-testid="stDataFrame"],
[data-testid="stTable"] {
    border-radius: var(--ios-radius) !important;
    overflow: hidden !important;
    box-shadow: var(--ios-shadow-card) !important;
    border: 0.5px solid var(--ios-separator) !important;
}

/* Table header */
[data-testid="stDataFrame"] [data-testid="glideDataEditor"] .dvn-header,
[data-testid="stDataFrame"] th {
    font-family: var(--ios-font) !important;
    font-weight: 600 !important;
    font-size: 0.8125rem !important;
    color: var(--ios-secondary-label) !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
}

/* Table cells */
[data-testid="stDataFrame"] td,
[data-testid="stDataFrame"] [data-testid="glideDataEditor"] .dvn-cell {
    font-family: var(--ios-font) !important;
    font-size: 0.9375rem !important;
    padding: 10px 12px !important;
}

/* Alternating row colors are handled by Streamlit's glide-data-grid.
   We override the grid background for a cleaner look. */
[data-testid="stDataFrame"] [data-testid="glideDataEditor"] {
    border-radius: var(--ios-radius) !important;
}


/* ==========================================================
   EXPANDER — iOS Disclosure Group
   ========================================================== */
[data-testid="stExpander"] {
    border-radius: var(--ios-radius) !important;
    border: 0.5px solid var(--ios-separator) !important;
    overflow: hidden !important;
    box-shadow: var(--ios-shadow-sm) !important;
    margin-bottom: 10px !important;
    background: var(--ios-card-bg) !important;
}

[data-testid="stExpander"] summary {
    font-family: var(--ios-font) !important;
    font-weight: 600 !important;
    font-size: 1rem !important;
    padding: 14px 16px !important;
    border-radius: var(--ios-radius) !important;
}

[data-testid="stExpander"] summary:hover {
    background: var(--ios-gray6) !important;
}

/* Expander content area */
[data-testid="stExpander"] [data-testid="stExpanderDetails"] {
    padding: 0 16px 16px !important;
    border-top: 0.5px solid var(--ios-separator) !important;
}


/* ==========================================================
   PROGRESS BAR — iOS Rounded Capsule
   ========================================================== */
[data-testid="stProgress"] > div > div {
    border-radius: 99px !important;
    height: 6px !important;
    background-color: var(--ios-gray5) !important;
}

[data-testid="stProgress"] > div > div > div {
    border-radius: 99px !important;
    background: linear-gradient(90deg, var(--ios-blue), var(--ios-teal)) !important;
}


/* ==========================================================
   SPINNER — iOS Activity Indicator Feel
   ========================================================== */
.stSpinner > div {
    border-top-color: var(--ios-blue) !important;
}


/* ==========================================================
   CHARTS — Rounded Container
   ========================================================== */
[data-testid="stArrowVegaLiteChart"],
[data-testid="stVegaLiteChart"],
.stChart {
    border-radius: var(--ios-radius) !important;
    overflow: hidden !important;
    box-shadow: var(--ios-shadow-card) !important;
    padding: 8px !important;
    background: var(--ios-card-bg) !important;
    border: 0.5px solid var(--ios-separator) !important;
    margin-bottom: 12px !important;
}


/* ==========================================================
   DIVIDERS / SEPARATORS — iOS Hairline
   ========================================================== */
hr,
[data-testid="stMarkdownContainer"] hr {
    border: none !important;
    border-top: 0.5px solid var(--ios-separator) !important;
    margin: 20px 0 !important;
}


/* ==========================================================
   FORM — iOS Grouped Style
   ========================================================== */
[data-testid="stForm"] {
    background: var(--ios-card-bg) !important;
    border-radius: var(--ios-radius-lg) !important;
    padding: var(--ios-padding-lg) !important;
    border: 0.5px solid var(--ios-separator) !important;
    box-shadow: var(--ios-shadow-card) !important;
}


/* ==========================================================
   COLUMNS — Better Gap on Mobile
   ========================================================== */
@media (max-width: 640px) {
    [data-testid="stHorizontalBlock"] {
        gap: 8px !important;
    }

    /* Stack columns on very small screens */
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        min-width: 0 !important;
    }
}


/* ==========================================================
   CUSTOM COMPONENT CLASSES (used by Python helpers below)
   ========================================================== */

/* Score Card */
.ios-score-card {
    background: var(--ios-card-bg);
    border-radius: var(--ios-radius);
    padding: 16px;
    box-shadow: var(--ios-shadow-card);
    border: 0.5px solid var(--ios-separator);
    text-align: center;
    transition: transform var(--ios-transition);
}

.ios-score-card:hover {
    transform: translateY(-2px);
}

.ios-score-card .score-label {
    font-family: var(--ios-font);
    font-size: 0.8125rem;
    font-weight: 600;
    color: var(--ios-tertiary-label);
    margin-bottom: 4px;
    text-transform: none;
}

.ios-score-card .score-value {
    font-family: var(--ios-font);
    font-size: 2.25rem;
    font-weight: 800;
    letter-spacing: -0.03em;
    line-height: 1.1;
}

.ios-score-card .score-value.signal-green { color: var(--ios-green); }
.ios-score-card .score-value.signal-yellow { color: var(--ios-yellow); }
.ios-score-card .score-value.signal-red { color: var(--ios-red); }
.ios-score-card .score-value.signal-blue { color: var(--ios-blue); }

.ios-score-card .score-subtitle {
    font-family: var(--ios-font);
    font-size: 0.75rem;
    color: var(--ios-gray);
    margin-top: 4px;
}


/* Signal Badge */
.ios-signal-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 12px;
    border-radius: 99px;
    font-family: var(--ios-font);
    font-size: 0.8125rem;
    font-weight: 600;
    line-height: 1;
    white-space: nowrap;
}

.ios-signal-badge .signal-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}

.ios-signal-badge.badge-green {
    background: rgba(52, 199, 89, 0.12);
    color: var(--ios-green);
}
.ios-signal-badge.badge-green .signal-dot { background: var(--ios-green); }

.ios-signal-badge.badge-yellow {
    background: rgba(255, 149, 0, 0.12);
    color: var(--ios-yellow);
}
.ios-signal-badge.badge-yellow .signal-dot { background: var(--ios-yellow); }

.ios-signal-badge.badge-red {
    background: rgba(255, 59, 48, 0.12);
    color: var(--ios-red);
}
.ios-signal-badge.badge-red .signal-dot { background: var(--ios-red); }

.ios-signal-badge.badge-blue {
    background: rgba(0, 122, 255, 0.12);
    color: var(--ios-blue);
}
.ios-signal-badge.badge-blue .signal-dot { background: var(--ios-blue); }


/* Metric Ring */
.ios-metric-ring {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 16px;
}

.ios-metric-ring .ring-container {
    position: relative;
    width: 100px;
    height: 100px;
}

.ios-metric-ring svg {
    width: 100px;
    height: 100px;
    transform: rotate(-90deg);
}

.ios-metric-ring .ring-bg {
    fill: none;
    stroke: var(--ios-gray5);
    stroke-width: 8;
}

.ios-metric-ring .ring-fill {
    fill: none;
    stroke-width: 8;
    stroke-linecap: round;
    transition: stroke-dashoffset 0.8s cubic-bezier(0.25, 0.1, 0.25, 1);
}

.ios-metric-ring .ring-fill.ring-green { stroke: var(--ios-green); }
.ios-metric-ring .ring-fill.ring-yellow { stroke: var(--ios-yellow); }
.ios-metric-ring .ring-fill.ring-red { stroke: var(--ios-red); }
.ios-metric-ring .ring-fill.ring-blue { stroke: var(--ios-blue); }

.ios-metric-ring .ring-value {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    font-family: var(--ios-font);
    font-size: 1.5rem;
    font-weight: 800;
    letter-spacing: -0.03em;
    color: var(--ios-label);
}

.ios-metric-ring .ring-label {
    font-family: var(--ios-font);
    font-size: 0.8125rem;
    font-weight: 600;
    color: var(--ios-tertiary-label);
}


/* Section Header */
.ios-section-header {
    margin-top: 24px;
    margin-bottom: 12px;
}

.ios-section-header .section-title {
    font-family: var(--ios-font);
    font-size: 1.375rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: var(--ios-label);
    margin: 0 0 2px 0;
}

.ios-section-header .section-subtitle {
    font-family: var(--ios-font);
    font-size: 0.8125rem;
    color: var(--ios-tertiary-label);
    margin: 0;
}


/* Info Row (like iOS Settings row) */
.ios-info-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 13px 0;
    border-bottom: 0.5px solid var(--ios-separator);
    font-family: var(--ios-font);
}

.ios-info-row:last-child {
    border-bottom: none;
}

.ios-info-row .row-label {
    font-size: 1rem;
    font-weight: 400;
    color: var(--ios-label);
}

.ios-info-row .row-value {
    font-size: 1rem;
    font-weight: 500;
    color: var(--ios-secondary-label);
}


/* Stock List Item */
.ios-stock-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    background: var(--ios-card-bg);
    border-bottom: 0.5px solid var(--ios-separator);
    font-family: var(--ios-font);
    transition: background var(--ios-transition);
}

.ios-stock-item:first-child {
    border-radius: var(--ios-radius) var(--ios-radius) 0 0;
}

.ios-stock-item:last-child {
    border-radius: 0 0 var(--ios-radius) var(--ios-radius);
    border-bottom: none;
}

.ios-stock-item:only-child {
    border-radius: var(--ios-radius);
}

.ios-stock-item .stock-signal {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
}

.ios-stock-item .stock-signal.dot-green { background: var(--ios-green); }
.ios-stock-item .stock-signal.dot-yellow { background: var(--ios-yellow); }
.ios-stock-item .stock-signal.dot-red { background: var(--ios-red); }

.ios-stock-item .stock-info {
    flex: 1;
    min-width: 0;
}

.ios-stock-item .stock-name {
    font-size: 1rem;
    font-weight: 600;
    color: var(--ios-label);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.ios-stock-item .stock-id {
    font-size: 0.8125rem;
    color: var(--ios-tertiary-label);
}

.ios-stock-item .stock-score {
    font-size: 1.25rem;
    font-weight: 800;
    letter-spacing: -0.03em;
    text-align: right;
    min-width: 48px;
}

.ios-stock-item .stock-score.score-green { color: var(--ios-green); }
.ios-stock-item .stock-score.score-yellow { color: var(--ios-yellow); }
.ios-stock-item .stock-score.score-red { color: var(--ios-red); }


/* ==========================================================
   SCROLLBAR — Thin iOS Style
   ========================================================== */
::-webkit-scrollbar {
    width: 4px;
    height: 4px;
}

::-webkit-scrollbar-track {
    background: transparent;
}

::-webkit-scrollbar-thumb {
    background: var(--ios-gray3);
    border-radius: 99px;
}

::-webkit-scrollbar-thumb:hover {
    background: var(--ios-gray2);
}


/* ==========================================================
   MOBILE SAFE AREA & TOUCH
   ========================================================== */
@supports (padding-top: env(safe-area-inset-top)) {
    .main .block-container {
        padding-top: calc(1.5rem + env(safe-area-inset-top)) !important;
        padding-bottom: calc(4rem + env(safe-area-inset-bottom)) !important;
    }
}

/* Larger touch targets on mobile */
@media (max-width: 768px) {
    .stButton > button,
    .stFormSubmitButton > button {
        min-height: 50px !important;
        font-size: 1.0625rem !important;
    }

    [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input {
        min-height: 50px !important;
        font-size: 1rem !important;
    }

    /* Make metric values even larger on mobile */
    [data-testid="stMetricValue"] {
        font-size: 1.75rem !important;
    }
}


/* ==========================================================
   REDUCED MOTION
   ========================================================== */
@media (prefers-reduced-motion: reduce) {
    * {
        transition: none !important;
        animation: none !important;
        transform: none !important;
    }
}

</style>
"""

# ---------------------------------------------------------------------------
# Apply Theme
# ---------------------------------------------------------------------------
def apply():
    """Inject the iOS theme CSS into the Streamlit app.
    Call this once near the top of app.py, right after st.set_page_config().
    """
    st.markdown(IOS_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helper Components
# ---------------------------------------------------------------------------

def score_card(label: str, score: float, signal: str = "blue", subtitle: str = ""):
    """
    Render an iOS Health-style score card.

    Args:
        label: Title above the number (e.g. "技術面")
        score: Numeric score to display (e.g. 8.5)
        signal: Color signal — "green", "yellow", "red", or "blue"
        subtitle: Optional small text below the score (e.g. "/10")
    """
    if not subtitle:
        subtitle = "/10"
    html = f"""
    <div class="ios-score-card">
        <div class="score-label">{label}</div>
        <div class="score-value signal-{signal}">{score}</div>
        <div class="score-subtitle">{subtitle}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def signal_badge(signal: str, text: str = ""):
    """
    Render an iOS-style pill badge with a colored dot.

    Args:
        signal: "green", "yellow", "red", or "blue"
        text: Label text (if empty, uses default signal name)
    """
    default_labels = {
        "green": "買進",
        "yellow": "觀望",
        "red": "避開",
        "blue": "資訊",
    }
    display_text = text or default_labels.get(signal, signal)
    html = f"""
    <span class="ios-signal-badge badge-{signal}">
        <span class="signal-dot"></span>
        {display_text}
    </span>
    """
    st.markdown(html, unsafe_allow_html=True)


def metric_ring(value: float, max_value: float = 10, label: str = "",
                signal: str = ""):
    """
    Render a circular progress ring (like Apple Watch activity rings).

    Args:
        value: Current value
        max_value: Maximum value (default 10)
        label: Text below the ring
        signal: Force a color ("green"/"yellow"/"red"/"blue").
                If empty, auto-determines from value/max ratio.
    """
    ratio = min(value / max_value, 1.0) if max_value > 0 else 0
    circumference = 2 * 3.14159 * 42  # radius=42
    dash_offset = circumference * (1 - ratio)

    if not signal:
        if ratio >= 0.7:
            signal = "green"
        elif ratio >= 0.4:
            signal = "yellow"
        else:
            signal = "red"

    display_value = f"{value:.1f}" if isinstance(value, float) else str(value)

    html = f"""
    <div class="ios-metric-ring">
        <div class="ring-container">
            <svg viewBox="0 0 100 100">
                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                <circle class="ring-fill ring-{signal}" cx="50" cy="50" r="42"
                    stroke-dasharray="{circumference:.1f}"
                    stroke-dashoffset="{dash_offset:.1f}"/>
            </svg>
            <div class="ring-value">{display_value}</div>
        </div>
        <div class="ring-label">{label}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def section_header(title: str, subtitle: str = ""):
    """
    Render an iOS-style section header with large bold title.

    Args:
        title: Section title text
        subtitle: Optional description below the title
    """
    sub_html = f'<p class="section-subtitle">{subtitle}</p>' if subtitle else ""
    html = f"""
    <div class="ios-section-header">
        <p class="section-title">{title}</p>
        {sub_html}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def info_row(label: str, value: str):
    """
    Render an iOS Settings-style label/value row.

    Args:
        label: Left side label
        value: Right side value
    """
    html = f"""
    <div class="ios-info-row">
        <span class="row-label">{label}</span>
        <span class="row-value">{value}</span>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def info_group(rows: list):
    """
    Render a group of info rows inside a card container.

    Args:
        rows: List of (label, value) tuples
    """
    inner = ""
    for label, value in rows:
        inner += f"""
        <div class="ios-info-row">
            <span class="row-label">{label}</span>
            <span class="row-value">{value}</span>
        </div>
        """
    html = f"""
    <div style="background: var(--ios-card-bg); border-radius: var(--ios-radius);
                padding: 2px 16px; box-shadow: var(--ios-shadow-card);
                border: 0.5px solid var(--ios-separator);">
        {inner}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def stock_list_item(stock_id: str, name: str, score: float, signal: str = ""):
    """
    Render a single stock item row (iOS list cell style).

    Args:
        stock_id: Stock ticker
        name: Stock name
        score: Overall score
        signal: "green"/"yellow"/"red" (auto-detected if empty)
    """
    if not signal:
        if score >= 7:
            signal = "green"
        elif score >= 4:
            signal = "yellow"
        else:
            signal = "red"

    html = f"""
    <div class="ios-stock-item">
        <div class="stock-signal dot-{signal}"></div>
        <div class="stock-info">
            <div class="stock-name">{name}</div>
            <div class="stock-id">{stock_id}</div>
        </div>
        <div class="stock-score score-{signal}">{score}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def stock_list(stocks: list):
    """
    Render a grouped list of stock items in an iOS card.

    Args:
        stocks: List of dicts with keys: stock_id, name, score, signal (optional)
    """
    inner = ""
    for s in stocks:
        sig = s.get("signal", "")
        score = s.get("score", s.get("avg", 0))
        if not sig:
            if score >= 7:
                sig = "green"
            elif score >= 4:
                sig = "yellow"
            else:
                sig = "red"

        inner += f"""
        <div class="ios-stock-item">
            <div class="stock-signal dot-{sig}"></div>
            <div class="stock-info">
                <div class="stock-name">{s.get('name', '')}</div>
                <div class="stock-id">{s.get('stock_id', '')}</div>
            </div>
            <div class="stock-score score-{sig}">{score}</div>
        </div>
        """

    html = f"""
    <div style="border-radius: var(--ios-radius); overflow: hidden;
                box-shadow: var(--ios-shadow-card);
                border: 0.5px solid var(--ios-separator);">
        {inner}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def score_row(sections: list):
    """
    Render a horizontal row of score cards (used for the 4-aspect analysis).
    Responsive: wraps to 2 columns on mobile.

    Args:
        sections: List of dicts with keys: label, score, signal
    """
    cards = ""
    for s in sections:
        signal = s.get("signal", "blue")
        cards += f"""
        <div class="ios-score-card" style="flex: 1; min-width: 80px;">
            <div class="score-label">{s['label']}</div>
            <div class="score-value signal-{signal}">{s['score']}</div>
            <div class="score-subtitle">/10</div>
        </div>
        """

    html = f"""
    <div style="display: flex; gap: 10px; flex-wrap: wrap;">
        {cards}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)
