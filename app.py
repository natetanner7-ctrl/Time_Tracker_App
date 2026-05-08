import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import date
from openai import OpenAI

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

# --- Initialize OpenAI Client ---
# We use a try/except block so the app doesn't crash if the key is missing or mistyped
try:
    api_key = st.secrets["OPENAI_API_KEY"]
    ai_client = OpenAI(api_key=api_key)
    ai_ready = True
except Exception as e:
    ai_ready = False

# --- Header & Logo ---
col1, col2 = st.columns([1, 5])

with col1:
    st.image("logo.png", width=200) 

with col2:
    st.title("Time Tracking & Payroll")

# --- 2. Establish Google Sheets Connection ---
conn = st.connection("gsheets", type=GSheetsConnection)

try:
    # Read Log data
    existing_data = conn.read(worksheet="Log", usecols=[0, 1, 2, 3, 4], ttl=0)
    existing_data = existing_data.dropna(how="all") 
    
    # Read Clients data
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
    st.error("Could not connect to the Google Sheet. Double-check your secrets.toml file.")
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
        
        export_cols = [col for col in ['Date', 'Day', 'Hours', 'Client', 'Task'] if col in display_df.columns]
        export_df = display_df[export_cols].copy()
        export_df['Date'] = export_df['Date'].dt.strftime('%Y-%m-%d')
        csv_data = export_df.to_csv(index=False).encode('utf-8')
        
        st.download_button(
            label=f"📥 Download {selected_period} Report",
            data=csv_data,
            file_name=f"Time_Report_{selected_period.replace(' ', '_')}.csv",
            mime="text/csv"
        )
        
        # --- NEW: AI SUMMARIZATION SECTION ---
        st.divider()
        st.subheader("🤖 AI Invoice Summaries")
        
        if ai_ready:
            if st.button(f"✨ Generate AI Summaries for {selected_period}"):
                with st.spinner("Compiling notes and generating summaries..."):
                    # Get unique clients for the selected period
                    unique_clients = display_df['Client'].dropna().unique()
                    
                    if len(unique_clients) == 0:
                        st.info("No clients found for this period.")
                    
                    for client_name in unique_clients:
                        # Get all tasks for this specific client
                        client_tasks = display_df[display_df['Client'] == client_name]['Task'].dropna().tolist()
                        
                        if not client_tasks:
                            continue
                            
                        # Format tasks into a bulleted list for the AI to read
                        task_bullet_points = "\n".join([f"- {task}" for task in client_tasks])
                        
                        # The Prompt that tells the AI exactly what to do
                        ai_prompt = f"You are a professional administrative assistant writing invoice descriptions. I will give you a list of rough task notes logged by an employee. Please combine these notes into a single, cohesive, formal paragraph that describes the work completed. Make it professional and concise. Do not use bullet points in your response. Here are the tasks:\n\n{task_bullet_points}"
                        
                        try:
                            # Send the prompt to OpenAI (using the fast, cost-effective gpt-4o-mini model)
                            response = ai_client.chat.completions.create(
                                model="gpt-4o-mini",
                                messages=[
                                    {"role": "system", "content": "You are a helpful and professional assistant."},
                                    {"role": "user", "content": ai_prompt}
                                ],
                                max_tokens=300
                            )
                            
                            # Extract the text the AI wrote
                            ai_summary = response.choices[0].message.content
                            
                            # Calculate total hours for this client so the boss has context
                            client_hours = display_df[display_df['Client'] == client_name]['Hours'].sum()
                            
                            # Display in a clean, expandable box
                            with st.expander(f"**{client_name}** | Total: {client_hours:.2f} hrs", expanded=True):
                                st.write(ai_summary)
                                
                        except Exception as e:
                            st.error(f"Failed to generate summary for {client_name}. Error: {e}")
        else:
            st.warning("⚠️ Cannot connect to OpenAI. Please ensure your OPENAI_API_KEY is properly set in the Streamlit Secrets.")

    else:
        st.info("No hours logged yet! Go to the 'Log New Hours' tab to get started.")

# ==========================================
# TAB 2: YOUR TIME ENTRY WORKSPACE
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
            
        task_description = st.text_area("Task(s) Completed", placeholder="E.g., Drafted rebuttal, reviewed case files...")
        
        submit_button = st.form_submit_button(label="Log Hours")

        if submit_button:
            if hours_worked > 0 and task_description.strip() != "":
                if "Please add clients" in client_selection or "Error" in client_selection:
                    st.warning("⚠️ Please add a valid client in the 'Client Management' tab first.")
                else:
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
                    
                    st.success(f"Successfully logged {hours_worked} hours for {client_selection}!")
                    st.rerun()
            elif hours_worked <= 0:
                st.warning("Please enter a valid number of hours (greater than 0).")
            else:
                st.warning("Please enter a brief description of the tasks completed.")

# ==========================================
# TAB 3: CLIENT MANAGEMENT
# ==========================================
with tab_clients:
    st.header("Manage Clients")
    st.write("Add new clients here to make them available in the Time Entry dropdown.")
    
    st.subheader("Current Clients")
    if not clients_data.empty and 'Client Name' in clients_data.columns:
        st.dataframe(clients_data, use_container_width=True, hide_index=True)
    else:
        st.info("No clients found. Add one below.")

    with st.form(key="add_client_form", clear_on_submit=True):
        new_client_name = st.text_input("New Client / Case Name", placeholder="E.g., Client C - Doe Case")
        add_client_button = st.form_submit_button("➕ Add Client")
        
        if add_client_button:
            if new_client_name.strip() != "":
                if new_client_name in client_list:
                    st.warning("This client already exists!")
                else:
                    new_client_row = pd.DataFrame([{"Client Name": new_client_name}])
                    updated_clients_df = pd.concat([clients_data, new_client_row], ignore_index=True)
                    
                    conn.update(worksheet="Clients", data=updated_clients_df)
                    st.success(f"Added '{new_client_name}' to the database!")
                    st.rerun()
            else:
                st.warning("Client name cannot be blank.")