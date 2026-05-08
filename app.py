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
        gemini_error = "GEMINI_API_KEY is missing in secrets."
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
    # Reading 6 columns: Date, Day, Hours, Client, Task, Status
    existing_data = conn.read(worksheet="Log", usecols=[0, 1, 2, 3, 4, 5], ttl=0)
    existing_data = existing_data.dropna(how="all") 
    
    # Ensure 'Status' column exists in our working dataframe
    if 'Status' not in existing_data.columns:
        existing_data['Status'] = "Unpaid"
    
    # Read Clients data for dropdowns
    try:
        clients_data = conn.read(worksheet="Clients", usecols=[0], ttl=0)
        clients_data = clients_data.dropna(how="all")
        client_list = clients_data['Client Name'].dropna().tolist() if not clients_data.empty else []
    except:
        client_list = []
except Exception as e:
    st.error(f"Connection Error: {e}")
    st.stop()

# --- 3. Create the Tab System ---
tab_dashboard, tab_entry, tab_clients = st.tabs(["📊 Payroll Dashboard", "⏱️ Log New Hours", "📁 Client Management"])

# ==========================================
# TAB 1: THE BOSS'S DASHBOARD
# ==========================================
with tab_dashboard:
    if not existing_data.empty:
        dashboard_data = existing_data.copy()
        dashboard_data['Date'] = pd.to_datetime(dashboard_data['Date'], format='mixed')
        dashboard_data['Month'] = dashboard_data['Date'].dt.strftime('%B %Y')
        
        st.subheader("Payroll Filter")
        col_rate, col_period = st.columns(2)
        with col_rate:
            hourly_rate = st.number_input("💵 Set Hourly Rate ($)", min_value=0.0, value=35.00, step=1.00)
        with col_period:
            months_available = ["All Time"] + dashboard_data['Month'].unique().tolist()
            selected_period = st.selectbox("📅 Select Pay Period", months_available)
            
        if selected_period == "All Time":
            display_df = dashboard_data.copy()
        else:
            display_df = dashboard_data[dashboard_data['Month'] == selected_period].copy()
            
        # Financial Metrics
        unpaid_hours = display_df[display_df['Status'] == "Unpaid"]['Hours'].sum()
        total_hours = display_df['Hours'].sum()
        
        m_col1, m_col2, m_col3 = st.columns(3)
        m_col1.metric("Total Hours", f"{total_hours:.2f}")
        m_col2.metric("Unpaid Hours", f"{unpaid_hours:.2f}")
        m_col3.metric("Unpaid Payout", f"${(unpaid_hours * hourly_rate):,.2f}")

        # --- FIXED CHART: Hours by Client (Paid vs Unpaid) ---
        st.write(f"### Hours by Client: {selected_period}")
        if not display_df.empty:
            # Group data by Client and Status[cite: 1]
            chart_data = display_df.groupby(['Client', 'Status'])['Hours'].sum().unstack(fill_value=0)
            
            # FIX: Force 'Paid' and 'Unpaid' columns to exist so colors don't crash[cite: 1]
            for col in ["Paid", "Unpaid"]:
                if col not in chart_data.columns:
                    chart_data[col] = 0.0
            
            # Reorder columns so colors are consistent (Paid=Red, Unpaid=Gray)[cite: 1]
            chart_data = chart_data[["Paid", "Unpaid"]]
            st.bar_chart(chart_data, color=["#A50000", "#555555"]) 
        
        # --- FUNCTION: Mark as Paid ---
        st.divider()
        if unpaid_hours > 0:
            if st.button(f"✅ Mark all '{selected_period}' entries as Paid"):
                # Define which rows to update based on the filter[cite: 1]
                if selected_period == "All Time":
                    existing_data['Status'] = "Paid"
                else:
                    # Update only rows that match the selected Month[cite: 1]
                    month_mask = pd.to_datetime(existing_data['Date']).dt.strftime('%B %Y') == selected_period
                    existing_data.loc[month_mask, 'Status'] = "Paid"
                
                conn.update(worksheet="Log", data=existing_data)
                st.success(f"Updated all entries for {selected_period} to Paid!")
                st.rerun()

        # AI Summary Section
        st.divider()
        st.subheader("🤖 AI Invoice Summaries")
        if ai_ready:
            try:
                available_models = [m.name.replace('models/', '') for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                selected_model = st.selectbox("Select API Model:", available_models)
                
                if st.button(f"✨ Generate Summaries for {selected_period}"):
                    model = genai.GenerativeModel(selected_model)
                    for client_name in display_df['Client'].unique():
                        tasks = display_df[display_df['Client'] == client_name]['Task'].tolist()
                        task_str = "\n".join([str(t) for t in tasks])
                        prompt = f"Combine these task notes into a professional invoice summary paragraph for {client_name}. No bullets: {task_str}"
                        response = model.generate_content(prompt)
                        with st.expander(f"**{client_name}**"):
                            st.write(response.text)
            except Exception as e:
                st.error(f"AI Error: {e}")
    else:
        st.info("No hours logged yet.")

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
        with col2:
            hours_worked = st.number_input("Hours Worked", min_value=0.0, step=0.25)
        with col3:
            client_selection = st.selectbox("Client / Case", options=client_list if client_list else ["No Clients Found"])
        
        task_description = st.text_area("Task(s) Completed")
        submit_button = st.form_submit_button(label="Log Hours")

        if submit_button and hours_worked > 0:
            new_row = pd.DataFrame([{
                "Date": entry_date.strftime("%Y-%m-%d"),
                "Day": day_of_week,
                "Hours": hours_worked,
                "Client": client_selection,
                "Task": task_description,
                "Status": "Unpaid"  # Defaults to Unpaid[cite: 1]
            }])
            
            # Keep columns clean for the concat[cite: 1]
            cols_to_keep = ["Date", "Day", "Hours", "Client", "Task", "Status"]
            clean_existing = existing_data[[c for c in cols_to_keep if c in existing_data.columns]]
            
            updated_df = pd.concat([clean_existing, new_row], ignore_index=True)
            conn.update(worksheet="Log", data=updated_df)
            st.success(f"Logged hours for {client_selection}!")
            st.rerun()

# ==========================================
# TAB 3: CLIENT MANAGEMENT
# ==========================================
with tab_clients:
    st.header("Manage Clients")
    if not client_list:
        st.info("Add your first client below.")
    else:
        st.dataframe(pd.DataFrame(client_list, columns=["Client Name"]), use_container_width=True, hide_index=True)

    with st.form("add_client"):
        new_c = st.text_input("Client Name")
        if st.form_submit_button("Add") and new_c:
            new_client_df = pd.DataFrame([{"Client Name": new_c}])
            updated_clients = pd.concat([pd.DataFrame(client_list, columns=["Client Name"]), new_client_df])
            conn.update(worksheet="Clients", data=updated_clients)
            st.success("Added!")
            st.rerun()