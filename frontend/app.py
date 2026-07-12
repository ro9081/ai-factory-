"""
app.py — Streamlit dashboard for the AI Factory POC.

Layout:
  ┌─────────────────────────────────────────────────────────┐
  │  Sidebar: Create Story form                             │
  ├─────────────────────────────────────────────────────────┤
  │  Main:    Story card grid (status badges + run button)  │
  │           ↓ click card                                  │
  │           Comment thread view                           │
  └─────────────────────────────────────────────────────────┘

Run with:  streamlit run frontend/app.py
Requires:  backend running at http://localhost:8000
"""
import re
import httpx
import streamlit as st
from datetime import datetime, timezone
from fpdf import FPDF


# ─── PDF Generator ──────────────────────────────────────────────────────────

class _PDF(FPDF):
    """Custom FPDF subclass with a footer showing page numbers."""
    def header(self):
        pass  # no default header

    def footer(self):
        self.set_y(-13)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"AI Factory PRD  |  Page {self.page_no()}", align="C")


def _clean(text: str) -> str:
    """Strip markdown syntax for plain-text PDF rendering."""
    # Bold / italic
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*",     r"\1", text)
    # Inline code
    text = re.sub(r"`(.+?)`",       r"\1", text)
    # Encode to latin-1 safe (replace unsupported chars)
    return text.encode("latin-1", "replace").decode("latin-1")


def generate_prd_pdf(story_title: str, prd_markdown: str) -> bytes:
    """
    Convert a Markdown PRD string into a styled PDF and return raw bytes.
    Uses fpdf2 — pure Python, no system dependencies.
    """
    pdf = _PDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(left=18, top=18, right=18)
    pdf.add_page()

    # ── Cover title ──────────────────────────────────────────────
    safe_title = story_title.encode("latin-1", "replace").decode("latin-1")
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(60, 60, 120)
    pdf.multi_cell(0, 10, safe_title, align="C")
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(160, 160, 160)
    pdf.cell(0, 6, "Product Requirements Document", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_draw_color(200, 200, 220)
    pdf.set_line_width(0.5)
    pdf.line(18, pdf.get_y(), 192, pdf.get_y())
    pdf.ln(8)

    # ── Body ─────────────────────────────────────────────────────
    for line in prd_markdown.split("\n"):
        stripped = line.rstrip()

        if stripped.startswith("# "):
            pdf.set_font("Helvetica", "B", 18)
            pdf.set_text_color(40, 40, 100)
            pdf.ln(4)
            pdf.multi_cell(0, 9, _clean(stripped[2:]))
            pdf.ln(2)

        elif stripped.startswith("## "):
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(60, 80, 160)
            pdf.ln(5)
            # Underline via line
            pdf.multi_cell(0, 8, _clean(stripped[3:]))
            ypos = pdf.get_y()
            pdf.set_draw_color(180, 190, 230)
            pdf.line(18, ypos, 192, ypos)
            pdf.ln(3)

        elif stripped.startswith("### "):
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(80, 80, 80)
            pdf.ln(3)
            pdf.multi_cell(0, 7, _clean(stripped[4:]))
            pdf.ln(1)

        elif stripped.startswith("- [ ] ") or stripped.startswith("- [x] "):
            checked = "[x]" in stripped
            mark = "[x]" if checked else "[ ]"
            pdf.set_font("Courier", "", 10)
            pdf.set_text_color(60, 60, 60)
            pdf.set_x(24)
            pdf.multi_cell(0, 6, f"  {mark} " + _clean(stripped[6:]))

        elif stripped.startswith("- ") or stripped.startswith("* "):
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(60, 60, 60)
            pdf.set_x(24)
            pdf.multi_cell(0, 6, f"  -  " + _clean(stripped[2:]))

        elif stripped.startswith("---"):
            pdf.ln(3)
            pdf.set_draw_color(200, 200, 200)
            pdf.line(18, pdf.get_y(), 192, pdf.get_y())
            pdf.ln(3)

        elif stripped == "":
            pdf.ln(3)

        else:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(50, 50, 50)
            pdf.set_x(18)
            pdf.multi_cell(0, 6, _clean(stripped))

    return bytes(pdf.output())

# ─── Config ─────────────────────────────────────────────────────────────────

API_URL = "http://localhost:8000/graphql"

STATUS_COLORS = {
    "Draft":       "#6B7280",   # grey
    "Clarifying":  "#F59E0B",   # amber
    "Green_Light": "#10B981",   # emerald
    "Accepted":    "#6366F1",   # indigo
}

# ─── Page config ────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="AI Factory — Story Dashboard",
    page_icon="cog",

    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ─────────────────────────────────────────────────────────────

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* Dark glassmorphism background */
    .stApp {
        background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
        min-height: 100vh;
    }

    /* Story card */
    .story-card {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 16px;
        padding: 20px;
        margin-bottom: 16px;
        backdrop-filter: blur(12px);
        transition: all 0.25s ease;
        cursor: pointer;
    }
    .story-card:hover {
        background: rgba(255, 255, 255, 0.09);
        border-color: rgba(255, 255, 255, 0.25);
        transform: translateY(-2px);
        box-shadow: 0 8px 32px rgba(0,0,0,0.3);
    }

    /* Status badge */
    .status-badge {
        display: inline-block;
        padding: 3px 12px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0.5px;
        color: #fff;
    }

    /* Comment bubble */
    .comment-pm {
        background: rgba(99, 102, 241, 0.15);
        border-left: 3px solid #6366F1;
        border-radius: 0 12px 12px 0;
        padding: 12px 16px;
        margin: 8px 0;
    }
    .comment-agent {
        background: rgba(16, 185, 129, 0.12);
        border-left: 3px solid #10B981;
        border-radius: 0 12px 12px 0;
        padding: 12px 16px;
        margin: 8px 0;
    }
    .comment-author {
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        margin-bottom: 4px;
        opacity: 0.7;
    }
    .comment-text {
        font-size: 14px;
        line-height: 1.6;
        white-space: pre-wrap;
        word-break: break-word;
    }
    .comment-ts {
        font-size: 10px;
        opacity: 0.45;
        margin-top: 4px;
    }

    /* Section header */
    .section-title {
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 1.5px;
        text-transform: uppercase;
        opacity: 0.5;
        margin-bottom: 12px;
    }

    /* Sidebar form */
    section[data-testid="stSidebar"] {
        background: rgba(15, 12, 41, 0.8) !important;
        border-right: 1px solid rgba(255,255,255,0.08);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ─── GraphQL helpers ─────────────────────────────────────────────────────────

def gql(query: str, variables: dict = None) -> dict:
    """Execute a GraphQL operation against the backend."""
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    
    headers = {}
    if st.session_state.get("token"):
        headers["Authorization"] = f"Bearer {st.session_state['token']}"
        
    try:
        resp = httpx.post(API_URL, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            error_msg = data["errors"][0].get("message", "Unknown error occurred.")
            st.error(f"{error_msg}")
            return {}
        return data.get("data", {})
    except httpx.ConnectError:
        st.error(
            "Cannot connect to backend. "
            "Make sure FastAPI is running:  `uvicorn backend.main:app --reload`"
        )
        return {}
    except Exception as exc:
        st.error(f"Request failed: {exc}")
        return {}


LOGIN_MUTATION = """
mutation Login($username: String!, $password: String!) {
  login(username: $username, password: $password) {
    token
    user { id username role }
  }
}
"""

REGISTER_MUTATION = """
mutation Register($username: String!, $password: String!, $role: String!) {
  register(username: $username, password: $password, role: $role) {
    token
    user { id username role }
  }
}
"""


STORIES_QUERY = """
query GetStories {
  stories {
    id title description status
    comments { id author text createdAt }
  }
}
"""

CREATE_STORY_MUTATION = """
mutation CreateStory($title: String!, $description: String!) {
  createStory(title: $title, description: $description) {
    id title status
  }
}
"""

RUN_WORKFLOW_MUTATION = """
mutation RunWorkflow($storyId: String!) {
  runWorkflow(storyId: $storyId) {
    id title description status
    comments { id author text createdAt }
  }
}
"""

SUBMIT_CLARIFICATION_MUTATION = """
mutation SubmitClarification($storyId: String!, $text: String!) {
  submitClarification(storyId: $storyId, text: $text) {
    id status
    comments { id author text createdAt }
  }
}
"""

ACCEPT_STORY_MUTATION = """
mutation AcceptStory($storyId: String!) {
  acceptStory(storyId: $storyId) {
    id status
  }
}
"""

DELETE_STORY_MUTATION = """
mutation DeleteStory($storyId: String!) {
  deleteStory(storyId: $storyId)
}
"""

# ─── Session state ────────────────────────────────────────────────────────────

if "selected_story_id" not in st.session_state:
    st.session_state.selected_story_id = None
if "refresh_key" not in st.session_state:
    st.session_state.refresh_key = 0
if "token" not in st.session_state:
    st.session_state.token = None
if "user" not in st.session_state:
    st.session_state.user = None
if "status_filter" not in st.session_state:
    st.session_state.status_filter = None

# ─── Live Analytics Widget ──────────────────────────────────────────────────
def render_analytics_widget():
    # Only fetch stats if logged in
    if not st.session_state.get("token"):
        return
        
    # We run a quick query just to get statuses
    stats_query = "{ stories { status } }"
    data = gql(stats_query)
    stories_list = data.get("stories", [])
    
    st.markdown("### Analytics")
    if not stories_list:
        st.write("No data yet.")
        return
        
    counts = {
        "Clarifying": sum(1 for s in stories_list if s["status"] == "Clarifying"),
        "Green_Light": sum(1 for s in stories_list if s["status"] == "Green_Light"),
        "Accepted": sum(1 for s in stories_list if s["status"] == "Accepted"),
        "Draft": sum(1 for s in stories_list if s["status"] == "Draft"),
    }
    
    c1, c2 = st.columns(2)
    with c1:
        if st.button(f"Clarifying: {counts['Clarifying']}", use_container_width=True, type="primary" if st.session_state.status_filter == "Clarifying" else "secondary"):
            st.session_state.status_filter = "Clarifying"
            st.rerun()
        if st.button(f"Accepted: {counts['Accepted']}", use_container_width=True, type="primary" if st.session_state.status_filter == "Accepted" else "secondary"):
            st.session_state.status_filter = "Accepted"
            st.rerun()
    with c2:
        if st.button(f"Green Light: {counts['Green_Light']}", use_container_width=True, type="primary" if st.session_state.status_filter == "Green_Light" else "secondary"):
            st.session_state.status_filter = "Green_Light"
            st.rerun()
        if st.button(f"Draft: {counts['Draft']}", use_container_width=True, type="primary" if st.session_state.status_filter == "Draft" else "secondary"):
            st.session_state.status_filter = "Draft"
            st.rerun()
            
    if st.session_state.status_filter:
        if st.button("Clear Filter", use_container_width=True):
            st.session_state.status_filter = None
            st.rerun()
    st.divider()


# ─── Login Screen ─────────────────────────────────────────────────────────────
def render_login_screen():
    st.markdown("<h1 style='text-align:center'>AI Factory Login</h1>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns([1, 1, 1])
    with c2:
        tab1, tab2 = st.tabs(["Login", "Register"])
        
        with tab1:
            with st.form("login_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Login", use_container_width=True)
                if submitted:
                    username_clean = username.strip() if username else ""
                    if not username_clean or not password:
                        st.error("Username and password are required.")
                    elif len(password) < 8:
                        st.error("Password must be at least 8 characters long.")
                    else:
                        res = gql(LOGIN_MUTATION, {"username": username_clean, "password": password})
                        if res and res.get("login"):
                            st.session_state.token = res["login"]["token"]
                            st.session_state.user = res["login"]["user"]
                            st.rerun()
                        
        with tab2:
            with st.form("register_form"):
                reg_username = st.text_input("Username")
                reg_password = st.text_input("Password", type="password")
                reg_role = st.selectbox("Role", ["PM", "Engineer", "Admin"])
                reg_submit = st.form_submit_button("Register", use_container_width=True)
                if reg_submit:
                    reg_username_clean = reg_username.strip() if reg_username else ""
                    if not reg_username_clean or not reg_password:
                        st.error("Username and password are required.")
                    elif len(reg_password) < 8:
                        st.error("Password must be at least 8 characters long.")
                    else:
                        res = gql(REGISTER_MUTATION, {"username": reg_username_clean, "password": reg_password, "role": reg_role})
                        if res and res.get("register"):
                            st.session_state.token = res["register"]["token"]
                            st.session_state.user = res["register"]["user"]
                            st.rerun()

# ─── Sidebar: Create Story ────────────────────────────────────────────────────

if not st.session_state.get("token"):
    render_login_screen()
    st.stop()

with st.sidebar:
    st.markdown("## AI Factory")
    st.markdown("*Tracer Bullet POC*")
    
    # User Profile
    user = st.session_state.user
    st.markdown(f"**👤 {user['username']}** (`{user['role']}`)")
    if st.button("Logout", use_container_width=True):
        st.session_state.token = None
        st.session_state.user = None
        st.rerun()

    st.divider()
    
    # Analytics Widget
    render_analytics_widget()

    if user["role"] == "PM":
        st.markdown("### New Story")

    with st.form("create_story_form", clear_on_submit=True):
        new_title = st.text_input("Title", placeholder="e.g. User Auth Flow")
        new_desc = st.text_area(
            "Description",
            placeholder="Describe the feature or user story in detail...",
            height=120,
        )
        submitted = st.form_submit_button("Create Story", use_container_width=True)

    if submitted:
        if new_title.strip() and new_desc.strip():
            with st.spinner("Creating story..."):
                result = gql(
                    CREATE_STORY_MUTATION,
                    {"title": new_title.strip(), "description": new_desc.strip()},
                )
            if result.get("createStory"):
                st.success(f"Story created: **{result['createStory']['title']}**")
                st.session_state.refresh_key += 1
                st.rerun()
        else:
            st.warning("Both title and description are required.")

    st.divider()
    st.markdown("### Legend")
    for status, color in STATUS_COLORS.items():
        st.markdown(
            f'<span class="status-badge" style="background:{color}">'
            f'{status}</span>',
            unsafe_allow_html=True,
        )
        st.markdown("")

# ─── Main panel ──────────────────────────────────────────────────────────────

col_header, col_refresh = st.columns([8, 1])
with col_header:
    st.markdown("# Story Dashboard")
with col_refresh:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Refresh", help="Refresh stories"):
        st.session_state.refresh_key += 1
        st.session_state.selected_story_id = None
        st.rerun()

# Fetch all stories
_ = st.session_state.refresh_key  # consume key to force re-render
data = gql(STORIES_QUERY)
stories = data.get("stories", [])

if st.session_state.status_filter:
    stories = [s for s in stories if s["status"] == st.session_state.status_filter]

if not stories:
    st.markdown(
        """
        <div style="text-align:center; padding: 60px 0; opacity:0.4">
            <div style="font-size:18px; margin-top:12px">No stories yet.</div>
            <div style="font-size:14px; margin-top:6px">Create one in the sidebar.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    # ── Story card grid ──────────────────────────────────────────────────────
    selected_story = None

    # Find currently selected story object
    if st.session_state.selected_story_id:
        selected_story = next(
            (s for s in stories if s["id"] == st.session_state.selected_story_id), None
        )

    # Render cards in 3 columns
    cols = st.columns(3)
    for i, story in enumerate(stories):
        col = cols[i % 3]
        status = story["status"]
        color = STATUS_COLORS.get(status, "#6B7280")
        comment_count = len(story.get("comments", []))
        is_selected = story["id"] == st.session_state.selected_story_id

        with col:
            border_style = (
                "border: 1px solid rgba(99,102,241,0.6);" if is_selected
                else "border: 1px solid rgba(255,255,255,0.1);"
            )
            st.markdown(
                f"""
                <div class="story-card" style="{border_style}">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px;">
                        <span class="status-badge" style="background:{color}">{status}</span>
                        <span style="font-size:11px; opacity:0.4">{comment_count} Comments</span>
                    </div>
                    <div style="font-size:15px; font-weight:600; margin-bottom:6px; line-height:1.4;">
                        {story['title']}
                    </div>
                    <div style="font-size:12px; opacity:0.55; line-height:1.5; display:-webkit-box;
                                -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden;">
                        {story['description']}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(
                "Open" if not is_selected else "Viewing",
                key=f"open_{story['id']}",
                use_container_width=True,
            ):
                st.session_state.selected_story_id = story["id"]
                st.rerun()

    # ── Story detail panel ───────────────────────────────────────────────────
    if selected_story:
        st.divider()
        status = selected_story["status"]
        color = STATUS_COLORS.get(status, "#6B7280")

        detail_col, action_col = st.columns([6, 2])
        with detail_col:
            st.markdown(
                f"## {selected_story['title']} "
                f'<span class="status-badge" style="background:{color}; vertical-align:middle;">'
                f"{status}</span>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div style='font-size:14px; opacity:0.6; margin-top:-8px;'>{selected_story['description']}</div>",
                unsafe_allow_html=True,
            )
        with action_col:
            st.markdown("<br>", unsafe_allow_html=True)

            # Determine if PM has already submitted answers (PM comment exists)
            comments = selected_story.get("comments", [])
            has_pm_answer = any(c["author"] == "PM" for c in comments)

            if status == "Clarifying" and not has_pm_answer:
                # Prompt PM to answer first before re-running
                st.info("Please answer the questions below to continue the workflow.")
            else:
                run_label = {
                    "Draft": "Start Workflow",
                    "Clarifying": "Continue Workflow",
                    "Green_Light": "Re-Run Workflow",
                    "Accepted": "Re-Run Workflow",
                }.get(status, "Run")
                if st.button(run_label, key="run_workflow_btn", use_container_width=True, type="primary"):
                    with st.spinner("Running LangGraph pipeline via Groq..."):
                        result = gql(
                            RUN_WORKFLOW_MUTATION,
                            {"storyId": selected_story["id"]},
                        )
                    if result.get("runWorkflow"):
                        updated = result["runWorkflow"]
                        new_status = updated["status"]
                        st.success(f"Done! Status: **{new_status}**")
                        st.session_state.refresh_key += 1
                        st.rerun()

            # PDF download — find the PRD comment (agent comment starting with # heading)
            prd_comment = next(
                (c for c in reversed(comments)
                 if c["author"] == "Agent" and c["text"].strip().startswith("#")),
                None,
            )
            if prd_comment:
                st.markdown("<br>", unsafe_allow_html=True)
                try:
                    pdf_bytes = generate_prd_pdf(
                        story_title=selected_story["title"],
                        prd_markdown=prd_comment["text"],
                    )
                    safe_fname = re.sub(r"[^\w\s-]", "", selected_story["title"]).strip().replace(" ", "_")
                    st.download_button(
                        label="Download PRD as PDF",
                        data=pdf_bytes,
                        file_name=f"{safe_fname}_PRD.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                    )
                except Exception as pdf_err:
                    st.warning(f"PDF generation error: {pdf_err}")

            if status == "Green_Light":
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("✅ Accept PRD", key="accept_story_btn", use_container_width=True):
                    with st.spinner("Accepting PRD..."):
                        res = gql(ACCEPT_STORY_MUTATION, {"storyId": selected_story["id"]})
                        if res.get("acceptStory"):
                            st.success("Story Accepted!")
                            st.session_state.refresh_key += 1
                            st.rerun()

            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🗑️ Delete Story", key="delete_story_btn", use_container_width=True):
                res = gql(DELETE_STORY_MUTATION, {"storyId": selected_story["id"]})
                if res.get("deleteStory"):
                    st.session_state.selected_story_id = None
                    st.session_state.refresh_key += 1
                    st.rerun()

        # ── Clarification / Revision reply box ──────
        is_revision = (status == "Green_Light")
        if (status == "Clarifying" and not has_pm_answer) or is_revision:
            st.markdown("<br>", unsafe_allow_html=True)
            
            box_title = "Suggest PRD Revisions" if is_revision else "Your Clarification Answers"
            box_desc = (
                "Provide feedback or suggest changes. The AI will regenerate the PRD." 
                if is_revision else 
                "Answer the agent's questions above. Be specific — your answers will "
                "be used directly by the PRD Writer to generate the document."
            )
            placeholder_text = (
                "e.g. Add a requirement for a mobile push notification, or restrict the API rate limit to 50/sec."
                if is_revision else
                "1. The primary user persona is...\n2. Success will be measured by...\n3. Key constraints include..."
            )
            btn_label = "Submit Revisions & Regenerate PRD" if is_revision else "Submit Answers & Continue"

            st.markdown(
                f'<div class="section-title">{box_title}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div style='font-size:13px; opacity:0.6; margin-bottom:12px;'>{box_desc}</div>",
                unsafe_allow_html=True,
            )
            with st.form(key=f"clarify_form_{selected_story['id']}", clear_on_submit=True):
                clarification_text = st.text_area(
                    "Your answers",
                    placeholder=placeholder_text,
                    height=180,
                    label_visibility="collapsed",
                )
                submit_col, _ = st.columns([2, 3])
                with submit_col:
                    submitted_clarification = st.form_submit_button(
                        btn_label, use_container_width=True, type="primary"
                    )

            if submitted_clarification:
                if clarification_text.strip():
                    with st.spinner("Saving answers & running workflow..."):
                        result = gql(
                            SUBMIT_CLARIFICATION_MUTATION,
                            {
                                "storyId": selected_story["id"],
                                "text": clarification_text.strip(),
                            },
                        )
                        if result.get("submitClarification"):
                            run_result = gql(
                                RUN_WORKFLOW_MUTATION,
                                {"storyId": selected_story["id"]},
                            )
                            if run_result.get("runWorkflow"):
                                new_status = run_result["runWorkflow"]["status"]
                                st.success(f"Workflow continued. Status: **{new_status}**")
                            st.session_state.refresh_key += 1
                            st.rerun()
                else:
                    st.warning("Please write your answers before submitting.")

        # ── Comment thread ────────────────────────────────────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(
            f'<div class="section-title">Comment Thread ({len(comments)})</div>',
            unsafe_allow_html=True,
        )

        if not comments:
            st.markdown(
                "<div style='opacity:0.4; font-size:13px;'>No comments yet. Run the workflow to start.</div>",
                unsafe_allow_html=True,
            )
        else:
            for c in comments:
                css_class = "comment-pm" if c["author"] == "PM" else "comment-agent"
                author_label = c["author"]
                # Format timestamp if available
                ts_str = ""
                if c.get("createdAt"):
                    try:
                        ts = datetime.fromisoformat(
                            c["createdAt"].replace("Z", "+00:00")
                        )
                        ts_str = ts.strftime("%b %d, %Y  %H:%M UTC")
                    except Exception:
                        ts_str = c["createdAt"]

                st.markdown(
                    f"""
                    <div class="{css_class}">
                        <div class="comment-author">{author_label}</div>
                        <div class="comment-text">{c['text']}</div>
                        <div class="comment-ts">{ts_str}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
