"""Centralized Theme System and Responsive Styling for Sports Lottery Decision System.

Provides unified CSS custom properties (variables) supporting both Light and Dark modes,
responsive card components, and cross-platform mobile numeric keypad enforcers.
"""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

# Theme design tokens for Python-generated charts, SVG, or components
THEME_TOKENS = {
    "brand_primary": "#ff4b4b",
    "brand_gradient_start": "#ff4b4b",
    "brand_gradient_end": "#ff9100",
    "line_green": "#06c755",
    "colors": {
        "blue": {"dark": "#38bdf8", "light": "#0284c7"},
        "amber": {"dark": "#fbbf24", "light": "#d97706"},
        "green": {"dark": "#4ade80", "light": "#16a34a"},
        "purple": {"dark": "#c084fc", "light": "#9333ea"},
        "red": {"dark": "#f87171", "light": "#dc2626"},
    },
}


def get_theme_css() -> str:
    """Return unified CSS custom properties and component rules for Light and Dark modes."""
    return """
    <style>
    /* ------------------------------------------------------------- */
    /* THEME VARIABLES (Default: Dark Mode)                          */
    /* ------------------------------------------------------------- */
    :root {
        --app-bg: #0e1117;
        --card-bg: #151824;
        --card-subtle-bg: #1c2136;
        --card-hover-bg: #22273d;
        --card-border: #2d334d;
        --card-border-subtle: rgba(255, 255, 255, 0.08);
        --text-primary: #f8fafc;
        --text-secondary: #94a3b8;
        --text-muted: #64748b;
        --card-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);

        --color-blue: #38bdf8;
        --color-blue-bg: rgba(56, 189, 248, 0.10);
        --color-blue-border: #0284c7;

        --color-amber: #fbbf24;
        --color-amber-bg: rgba(251, 191, 36, 0.10);
        --color-amber-border: #d97706;

        --color-green: #4ade80;
        --color-green-bg: rgba(74, 222, 128, 0.10);
        --color-green-border: #16a34a;

        --color-purple: #c084fc;
        --color-purple-bg: rgba(192, 132, 252, 0.10);
        --color-purple-border: #9333ea;

        --color-line: #06c755;
        --color-line-bg: rgba(6, 199, 85, 0.12);
        --color-line-border: #05963f;
    }

    /* ------------------------------------------------------------- */
    /* LIGHT MODE OVERRIDES                                          */
    /* Triggers automatically via system preference or Streamlit UI   */
    /* ------------------------------------------------------------- */
    @media (prefers-color-scheme: light) {
        :root {
            --app-bg: #f8fafc;
            --card-bg: #ffffff;
            --card-subtle-bg: #f8fafc;
            --card-hover-bg: #f1f5f9;
            --card-border: #e2e8f0;
            --card-border-subtle: #edf2f7;
            --text-primary: #0f172a;
            --text-secondary: #475569;
            --text-muted: #64748b;
            --card-shadow: 0 2px 8px rgba(0, 0, 0, 0.06), 0 1px 3px rgba(0, 0, 0, 0.04);

            --color-blue: #0284c7;
            --color-blue-bg: rgba(2, 132, 199, 0.08);
            --color-blue-border: #38bdf8;

            --color-amber: #d97706;
            --color-amber-bg: rgba(217, 119, 6, 0.08);
            --color-amber-border: #fbbf24;

            --color-green: #16a34a;
            --color-green-bg: rgba(22, 163, 74, 0.08);
            --color-green-border: #4ade80;

            --color-purple: #9333ea;
            --color-purple-bg: rgba(147, 51, 234, 0.08);
            --color-purple-border: #c084fc;

            --color-line: #05963f;
            --color-line-bg: rgba(6, 199, 85, 0.10);
            --color-line-border: #06c755;
        }
    }

    /* Support Streamlit explicit light data-theme attribute */
    [data-theme="light"], .stApp[data-theme="light"], div[data-baseweb="card"][data-theme="light"] {
        --app-bg: #f8fafc;
        --card-bg: #ffffff;
        --card-subtle-bg: #f8fafc;
        --card-hover-bg: #f1f5f9;
        --card-border: #e2e8f0;
        --card-border-subtle: #edf2f7;
        --text-primary: #0f172a;
        --text-secondary: #475569;
        --text-muted: #64748b;
        --card-shadow: 0 2px 8px rgba(0, 0, 0, 0.06), 0 1px 3px rgba(0, 0, 0, 0.04);

        --color-blue: #0284c7;
        --color-blue-bg: rgba(2, 132, 199, 0.08);
        --color-blue-border: #38bdf8;

        --color-amber: #d97706;
        --color-amber-bg: rgba(217, 119, 6, 0.08);
        --color-amber-border: #fbbf24;

        --color-green: #16a34a;
        --color-green-bg: rgba(22, 163, 74, 0.08);
        --color-green-border: #4ade80;

        --color-purple: #9333ea;
        --color-purple-bg: rgba(147, 51, 234, 0.08);
        --color-purple-border: #c084fc;

        --color-line: #05963f;
        --color-line-bg: rgba(6, 199, 85, 0.10);
        --color-line-border: #06c755;
    }

    /* ------------------------------------------------------------- */
    /* UNIFIED COMPONENT STYLES                                      */
    /* ------------------------------------------------------------- */

    /* Navbar / Header */
    header[data-testid="stHeader"], [data-testid="stHeader"] {
        background: var(--card-bg) !important;
        backdrop-filter: blur(12px) !important;
        -webkit-backdrop-filter: blur(12px) !important;
        border-bottom: 1px solid var(--card-border) !important;
        z-index: 99990 !important;
    }
    .block-container {
        padding-top: calc(3.6rem + env(safe-area-inset-top, 0px)) !important;
        padding-bottom: calc(2.5rem + env(safe-area-inset-bottom, 0px)) !important;
    }
    @media (max-width: 768px) {
        .block-container {
            padding-top: calc(4.8rem + env(safe-area-inset-top, 0px)) !important;
            padding-bottom: calc(3.0rem + env(safe-area-inset-bottom, 0px)) !important;
            padding-left: 0.75rem !important;
            padding-right: 0.75rem !important;
        }
        .brand-header {
            font-size: 1.55rem !important;
            margin-top: 0.4rem !important;
            line-height: 1.25 !important;
        }
        .brand-sub {
            font-size: 0.85rem !important;
            margin-bottom: 0.6rem !important;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 2px !important;
            flex-wrap: wrap !important;
        }
        .stTabs [data-baseweb="tab"] {
            padding: 6px 8px !important;
            font-size: 0.84rem !important;
        }
        .ticket-card {
            padding: 12px !important;
            margin-bottom: 12px !important;
        }
        .stButton button {
            min-height: 44px !important;
            font-size: 1rem !important;
        }
    }

    /* Brand Header */
    .brand-header {
        font-size: 2.2rem;
        font-weight: 900;
        background: linear-gradient(90deg, #ff4b4b, #ff9100);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.1rem;
    }
    .brand-sub {
        font-size: 1.02rem;
        color: var(--text-secondary);
        margin-bottom: 0.8rem;
    }

    /* Segmented Navigation Bar */
    div[data-testid="stSegmentedControl"] {
        width: 100% !important;
        display: flex !important;
        justify-content: center !important;
        margin: 6px 0 16px 0 !important;
    }
    div[data-testid="stSegmentedControl"] > div {
        display: flex !important;
        flex-wrap: wrap !important;
        gap: 6px !important;
        background: var(--card-bg) !important;
        padding: 4px !important;
        border-radius: 12px !important;
        border: 1px solid var(--card-border) !important;
        width: 100% !important;
        justify-content: space-around !important;
        box-shadow: var(--card-shadow) !important;
    }
    div[data-testid="stSegmentedControl"] button {
        flex: 1 1 auto !important;
        min-width: 68px !important;
        padding: 8px 12px !important;
        font-size: 0.90rem !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
        text-align: center !important;
        white-space: nowrap !important;
        color: var(--text-primary) !important;
    }
    @media (max-width: 600px) {
        div[data-testid="stSegmentedControl"] button {
            padding: 6px 4px !important;
            font-size: 0.80rem !important;
            min-width: 58px !important;
        }
    }

    /* Mobile Wallet Grid & Cards */
    .mobile-wallet-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 8px;
        margin-top: 6px;
        margin-bottom: 12px;
    }
    @media (min-width: 768px) {
        .mobile-wallet-grid {
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
        }
    }
    .mobile-wallet-card {
        background: var(--card-bg);
        border: 1px solid var(--card-border);
        border-radius: 10px;
        padding: 10px 12px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        box-shadow: var(--card-shadow);
        transition: transform 0.15s ease, border-color 0.15s ease;
    }
    .mobile-wallet-card:hover {
        transform: translateY(-1px);
        border-color: var(--card-border-subtle);
    }
    .mobile-wallet-card.card-blue { border-left: 4px solid var(--color-blue); }
    .mobile-wallet-card.card-amber { border-left: 4px solid var(--color-amber); }
    .mobile-wallet-card.card-green { border-left: 4px solid var(--color-green); }
    .mobile-wallet-card.card-purple { border-left: 4px solid var(--color-purple); }

    .mobile-wallet-card .m-label {
        font-size: 0.78rem;
        color: var(--text-secondary);
        margin-bottom: 2px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .mobile-wallet-card .m-value {
        font-size: 1.18rem;
        font-weight: 800;
        color: var(--text-primary);
        line-height: 1.25;
        letter-spacing: -0.02em;
    }
    .mobile-wallet-card .m-sub {
        font-size: 0.72rem;
        color: var(--text-muted);
        margin-top: 2px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    /* Profile / Auth Status Badge Card */
    .profile-badge-card {
        background: var(--card-bg);
        border: 1px solid var(--card-border);
        border-radius: 10px;
        padding: 12px 18px;
        margin-bottom: 12px;
        box-shadow: var(--card-shadow);
    }
    .profile-badge-card .p-label {
        font-size: 0.82rem;
        color: var(--text-secondary);
    }
    .profile-badge-card .p-name {
        font-size: 1.25rem;
        font-weight: bold;
        color: var(--text-primary);
        margin-top: 2px;
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 6px;
    }
    .profile-badge-card .p-tag {
        font-size: 0.78rem;
        background: var(--color-blue-bg);
        color: var(--color-blue);
        border: 1px solid var(--color-blue-border);
        padding: 2px 8px;
        border-radius: 4px;
        font-weight: normal;
    }

    /* Generic Themed Cards */
    .source-health-ribbon {
        background: var(--card-bg);
        border: 1px solid var(--card-border);
        border-radius: 8px;
        padding: 10px 16px;
        margin-bottom: 16px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        box-shadow: var(--card-shadow);
    }
    .wallet-metric-box {
        background: var(--card-bg);
        border: 1px solid var(--card-border);
        border-radius: 12px;
        padding: 16px;
        text-align: center;
        box-shadow: var(--card-shadow);
    }
    .ticket-card {
        background: var(--card-bg);
        border: 1px solid var(--card-border);
        border-radius: 12px;
        padding: 18px;
        margin-bottom: 14px;
        box-shadow: var(--card-shadow);
    }
    .why-box {
        background: var(--card-subtle-bg);
        border: 1px solid var(--card-border);
        border-radius: 8px;
        padding: 12px 16px;
        margin-top: 8px;
        margin-bottom: 12px;
        color: var(--text-primary);
    }
    .mobile-leg-card {
        background: var(--card-bg);
        border: 1px solid var(--card-border);
        border-radius: 8px;
        padding: 10px 14px;
        margin-bottom: 8px;
        box-shadow: var(--card-shadow);
    }
    .mobile-leg-card:hover {
        border-color: var(--color-blue);
    }

    /* Settled Tickets */
    .settled-ticket-card {
        background: var(--card-bg);
        border: 1px solid var(--card-border);
        border-radius: 10px;
        padding: 12px 14px;
        margin-bottom: 10px;
        box-shadow: var(--card-shadow);
    }
    .settled-ticket-card.won {
        border-left: 4px solid #10b981;
        background: linear-gradient(90deg, rgba(16, 185, 129, 0.08) 0%, var(--card-bg) 100%);
    }
    .settled-ticket-card.lost {
        border-left: 4px solid #64748b;
    }
    .settled-ticket-card.void {
        border-left: 4px solid var(--color-blue);
    }

    /* LINE Binding Tutorial Card */
    .line-guide-card {
        background: var(--card-bg);
        border: 1px solid var(--card-border);
        border-left: 5px solid #06c755;
        border-radius: 10px;
        padding: 16px 20px;
        margin-top: 12px;
        margin-bottom: 16px;
        box-shadow: var(--card-shadow);
    }
    .line-guide-card .lg-title {
        font-size: 1.08rem;
        font-weight: 700;
        color: var(--text-primary);
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 6px;
    }
    .line-guide-card .lg-sub {
        font-size: 0.88rem;
        color: var(--text-secondary);
        line-height: 1.5;
        margin-bottom: 10px;
    }
    .line-code-pill {
        display: inline-block;
        background: var(--card-subtle-bg);
        border: 1px dashed var(--color-line-border);
        color: var(--text-primary);
        padding: 6px 14px;
        border-radius: 6px;
        font-family: monospace;
        font-weight: 700;
        font-size: 1.02rem;
        margin: 4px 0;
    }
    .line-step {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        margin-top: 8px;
        font-size: 0.88rem;
        color: var(--text-secondary);
    }
    .line-step-num {
        background: #06c755;
        color: #ffffff;
        font-weight: bold;
        width: 20px;
        height: 20px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 0.75rem;
        flex-shrink: 0;
        margin-top: 2px;
    }

    /* Login Hero Card */
    .login-hero-card {
        background: var(--card-bg);
        border: 1px solid var(--card-border);
        border-radius: 12px;
        padding: 18px 22px;
        margin-bottom: 16px;
        box-shadow: var(--card-shadow);
    }
    .login-hero-title {
        font-size: 1.55rem;
        font-weight: 900;
        background: linear-gradient(90deg, #ff4b4b, #ff9100);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 4px;
    }
    .login-hero-subtitle {
        font-size: 0.90rem;
        color: var(--text-secondary);
    }
    </style>
    """


def inject_pwa_meta() -> None:
    """Inject iOS Safari / PWA web app metadata tags into the page head."""
    st.markdown(
        """
        <link rel="manifest" href="/app/static/manifest.json">
        <link rel="apple-touch-icon" href="/app/static/apple-touch-icon.png">
        <link rel="apple-touch-icon" sizes="180x180" href="/app/static/apple-touch-icon.png">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
        <meta name="apple-mobile-web-app-title" content="瘋狗流運彩">
        <meta name="theme-color" content="#ff4b4b">
        """,
        unsafe_allow_html=True,
    )


def inject_theme() -> None:
    """Inject centralized CSS styles into the current Streamlit page."""
    st.markdown(get_theme_css(), unsafe_allow_html=True)


def inject_mobile_numeric_keypad_enforcer() -> None:
    """Force mobile devices (iOS Safari, Android Chrome) to open the numeric keypad for PIN inputs.

    Executes inside an iframe via streamlit.components.v1.html so browsers reliably execute
    the JavaScript, accessing the parent DOM to set inputmode="numeric", pattern="[0-9]*",
    and autocomplete="one-time-code".
    """
    components.html(
        """
        <script>
        (function() {
            function patchInputs() {
                try {
                    const doc = window.parent.document;
                    if (!doc) return;
                    const inputs = doc.querySelectorAll('input');
                    inputs.forEach(function(el) {
                        const label = (el.getAttribute('aria-label') || '').toLowerCase();
                        const ph = (el.getAttribute('placeholder') || '').toLowerCase();
                        const id = (el.id || '').toLowerCase();
                        const name = (el.getAttribute('name') || '').toLowerCase();
                        const isPin = id.includes('pin') || ph.includes('pin') || label.includes('pin') || label.includes('碼') || name.includes('pin');
                        if (isPin) {
                            if (el.getAttribute('inputmode') !== 'numeric') {
                                el.setAttribute('inputmode', 'numeric');
                                el.setAttribute('pattern', '[0-9]*');
                                el.setAttribute('autocomplete', 'one-time-code');
                            }
                        }
                    });
                } catch (e) {
                    // Safe guard if running under cross-origin iframe
                }
            }
            patchInputs();
            // Periodic check in case Streamlit rerenders components
            const interval = setInterval(patchInputs, 600);
            setTimeout(function() { clearInterval(interval); }, 15000);

            // Also attach MutationObserver to parent document
            try {
                const doc = window.parent.document;
                if (doc && doc.body && !window.parent.__pinObserverAttached) {
                    const observer = new MutationObserver(patchInputs);
                    observer.observe(doc.body, { childList: true, subtree: true });
                    window.parent.__pinObserverAttached = true;
                }
            } catch (e) {}
        })();
        </script>
        """,
        height=0,
        width=0,
    )
