import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import date
import google.generativeai as genai

# --- 1. Page Configuration & Styling ---
st.set_page_config(page_title="VALIDOX Time Tracker", page_icon="⏱️", layout="centered")

st.markdown("""
    <style>
    div.stButton > button:first-child {
        background-color: #A50000;
        color: white;
        border: none;
    }
    div.stButton > button:first-child:hover {
        background-color: #800000;
        color: white;
    }
    </style>
""", unsafe_allow_html=True)

# --- Initialize Gemini AI Client ---
try:
    api_key = st.secrets.get("GEMINI_API_KEY")
    
    if api_key:
        genai.configure(api_key=api_key)
        ai_ready = True
        gemini_error = ""
    else:
        ai_ready = False
        seen_keys = list(st.secrets.keys())
        gemini_error = f"GEMINI_API_KEY is missing. Streamlit sees: {seen_keys}."
except Exception as e:
    ai_ready = False
    gemini_error = repr(e) 

# --- Header & Logo ---
col1, col2 = st.columns([1, 5])

with col1:
    st.image("logo.png", width=200) 

with col2:
    st.title("Time Tracking & Payroll")

# --- 2. Establish Google Sheets Connection ---
conn = st.connection("gsheets", type=GSheetsConnection)

try:
    # Reading 5 columns: Date, Day, Hours, Client, Task
    existing_data = conn.read(worksheet="Log", usecols=[0, 1, 2, 3, 4], ttl=0)
    existing_data = existing_data.dropna(how="all") 
    
    # Read Clients data for dynamic dropdowns
    try:
        clients_data = conn.read(worksheet="Clients", usecols=[0], ttl=0)
        clients_data = clients_data.dropna(how="all")
        if not clients_data.empty and 'Client Name' in clients_data.columns:
            client_list = clients_data['Client Name'].dropna().tolist()
        else:
            client_list = ["Please add clients in the Client Management tab"]
    except:
        client_list = ["Error: Could not find 'Clients' worksheet"]
        clients_data = pd.DataFrame(columns=["Client Name"])

except Exception as e:
    st.error("Could not connect to the Google Sheet. Check secrets.toml and Streamlit Cloud.")
    st.stop()

# --- 3. Create the Tab System ---
tab_dashboard, tab_entry, tab_clients = st.tabs(["📊 Payroll Dashboard", "⏱️ Log New Hours", "📁 Client Management"])

# ==========================================
# TAB 1: THE BOSS'S DASHBOARD
# ==========================================
with tab_dashboard:
    if not existing_data.empty and len(existing_data) > 0:
        dashboard_data = existing_data.copy()
        
        dashboard_data['Date'] = pd.to_datetime(dashboard_data['Date'], format='mixed')
        dashboard_data['Month'] = dashboard_data['Date'].dt.strftime('%B %Y')
        
        st.subheader("Payroll Filter")
        col_rate, col_period = st.columns(2)
        
        with col_rate:
            hourly_rate = st.number_input("💵 Set Hourly Rate ($)", min_value=0.0, value=35.00, step=1.00, format="%.2f")
            
        with col_period:
            months_available = ["All Time"] + dashboard_data['Month'].unique().tolist()
            selected_period = st.selectbox("📅 Select Pay Period", months_available)
            
        st.divider()
        
        if selected_period == "All Time":
            display_df = dashboard_data.copy()
        else:
            display_df = dashboard_data[dashboard_data['Month'] == selected_period].copy()
            
        total_hours = display_df['Hours'].sum()
        total_pay = total_hours * hourly_rate
        
        m_col1, m_col2 = st.columns(2)
        m_col1.metric(label="Total Hours", value=f"{total_hours:.2f} hrs")
        m_col2.metric(label="Total Payout Owed", value=f"${total_pay:,.2f}")
        
        if selected_period == "All Time":
            chart_data = display_df.groupby('Month')['Hours'].sum().reset_index()
            chart_data['Date_Sort'] = pd.to_datetime(chart_data['Month'])
            chart_data = chart_data.sort_values('Date_Sort').set_index('Month')
        else:
            chart_data = display_df.groupby('Date')['Hours'].sum().reset_index()
            chart_data['Date'] = chart_data['Date'].dt.strftime('%Y-%m-%d')
            chart_data = chart_data.set_index('Date')
            
        if not chart_data.empty:
            st.bar_chart(chart_data['Hours'], color="#A50000")
        
        # --- AI SUMMARIZATION SECTION ---
        st.divider()
        st.subheader("🤖 AI Invoice Summaries")
        
        if ai_ready:
            try:
                # NEW: Ask Google for a list of valid models your API key has access to
                available_models = []
                for m in genai.list_models():
                    if 'generateContent' in m.supported_generation_methods:
                        # Clean up the internal name formatting
                        clean_name = m.name.replace('models/', '')
                        available_models.append(clean_name)
                
                if not available_models:
                    st.error("Your API key works, but Google says your account has no access to any text generation models. Check your Google AI Studio account settings or region restrictions.")
                else:
                    # Create a dropdown so you can manually select a guaranteed-valid model
                    selected_model = st.selectbox("Select API Model (Fetched directly from Google):", available_models)
                    
                    if st.button(f"✨ Generate AI Summaries for {selected_period}"):
                        with st.spinner(f"Generating summaries using {selected_model}..."):
                            unique_clients = display_df['Client'].dropna().unique()
                            
                            if len(unique_clients) == 0:
                                st.info("No clients found for this period.")
                            
                            # Initialize the model using your selection
                            model = genai.GenerativeModel(selected_model)
                            
                            for client_name in unique_clients:
                                client_tasks = display_df[display_df['Client'] == client_name]['Task'].dropna().tolist()
                                
                                if not client_tasks:
                                    continue
                                    
                                task_bullet_points = "\n".join([f"- {task}" for task in client_tasks])
                                ai_prompt = (
                                    "You are a professional administrative assistant writing invoice descriptions. "
                                    "Combine these raw task notes into a single, cohesive, formal paragraph describing "
                                    "the work completed. Keep it professional, concise, and do not use bullet points. "
                                    f"Tasks for {client_name}:\n\n{task_bullet_points}"
                                )
                                
                                try:
                                    response = model.generate_content(ai_prompt)
                                    ai_summary = response.text
                                    client_hours = display_df[display_df['Client'] == client_name]['Hours'].sum()
                                    
                                    with st.expander(f"**{client_name}** | Total: {client_hours:.2f} hrs", expanded=True):
                                        st.write(ai_summary)
                                        
                                except Exception as e:
                                    st.error(f"Failed to generate summary for {client_name}. Error: {e}")
            except Exception as e:
                st.error(f"Failed to connect to Google's model list. Error: {e}")
        else:
            st.error(f"⚠️ {gemini_error}")

    else:
        st.info("No hours logged yet! Use the 'Log New Hours' tab.")

# ==========================================
# TAB 2: LOG NEW HOURS
# ==========================================
with tab_entry:
    st.header("Log New Hours")
    with st.form(key="time_entry_form", clear_on_submit=True):
        col1, col2, col3 = st.columns([1, 1, 1.5])
        with col1:
            entry_date = st.date_input("Date", value=date.today())
            day_of_week = entry_date.strftime("%A")
            st.text_input("Day", value=day_of_week, disabled=True) 
        with col2:
            hours_worked = st.number_input("Hours Worked", min_value=0.0, step=0.25, format="%.2f")
        with col3:
            client_selection = st.selectbox("Client / Case", options=client_list)
        task_description = st.text_area("Task(s) Completed", placeholder="Describe the work performed...")
        submit_button = st.form_submit_button(label="Log Hours")

        if submit_button:
            if hours_worked > 0 and task_description.strip() != "":
                new_row = pd.DataFrame([{
                    "Date": entry_date.strftime("%Y-%m-%d"),
                    "Day": day_of_week,
                    "Hours": hours_worked,
                    "Client": client_selection,
                    "Task": task_description
                }])
                cols_to_keep = ["Date", "Day", "Hours", "Client", "Task"]
                clean_existing_data = existing_data[[c for c in cols_to_keep if c in existing_data.columns]]
                updated_df = pd.concat([clean_existing_data, new_row], ignore_index=True)
                conn.update(worksheet="Log", data=updated_df)
                st.success(f"Logged {hours_worked} hours for {client_selection}!")
                st.rerun()

# ==========================================
# TAB 3: CLIENT MANAGEMENT
# ==========================================
with tab_clients:
    st.header("Manage Clients")
    if not clients_data.empty:
        st.dataframe(clients_data, use_container_width=True, hide_index=True)
    with st.form(key="add_client_form", clear_on_submit=True):
        new_client_name = st.text_input("New Client / Case Name")
        if st.form_submit_button("➕ Add Client"):
            if new_client_name.strip() != "":
                new_row = pd.DataFrame([{"Client Name": new_client_name}])
                updated_clients = pd.concat([clients_data, new_row], ignore_index=True)
                conn.update(worksheet="Clients", data=updated_clients)
                st.success(f"Added '{new_client_name}'!")
                st.rerun()