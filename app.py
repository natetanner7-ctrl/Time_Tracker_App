import streamlit as st
import altair as alt
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

# --- 2. PIN CODE AUTHENTICATION ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image("logo.png", width=150)
        st.write("### 🔒 Secure App Login")
        pin_input = st.text_input("Enter PIN Code", type="password")
        
        if st.button("Unlock"):
            correct_pin = str(st.secrets.get("APP_PIN", "1234"))
            if pin_input == correct_pin:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Incorrect PIN. Please try again.")
    st.stop()

# --- 3. Initialize Gemini AI Client ---
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

# --- 4. Establish Google Sheets Connection ---
conn = st.connection("gsheets", type=GSheetsConnection)

try:
    # Now reading 8 columns to include Entry Type and Fee Amount
    existing_data = conn.read(worksheet="Log", usecols=[0, 1, 2, 3, 4, 5, 6, 7], ttl=0)
    existing_data = existing_data.dropna(how="all") 
    
    # Retroactively fill new columns for old data so the app doesn't break
    if 'Status' not in existing_data.columns:
        existing_data['Status'] = "Unpaid"
    if 'Entry Type' not in existing_data.columns:
        existing_data['Entry Type'] = "Hourly Work"
    if 'Fee Amount' not in existing_data.columns:
        existing_data['Fee Amount'] = 0.0
        
    existing_data['Fee Amount'] = pd.to_numeric(existing_data['Fee Amount'], errors='coerce').fillna(0.0)
    
    try:
        clients_data = conn.read(worksheet="Clients", usecols=[0], ttl=0)
        clients_data = clients_data.dropna(how="all")
        client_list = clients_data['Client Name'].dropna().tolist() if not clients_data.empty else []
    except:
        client_list = []
except Exception as e:
    st.error(f"Connection Error: {e}")
    st.stop()

# --- 5. Create the Tab System ---
tab_dashboard, tab_entry, tab_clients = st.tabs(["📊 Payroll Dashboard", "⏱️ Log New Work", "📁 Client Management"])

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
            
        # Hybrid Metrics Calculation
        unpaid_df = display_df[display_df['Status'] == "Unpaid"]
        
        total_hours = display_df['Hours'].sum()
        unpaid_hours = unpaid_df['Hours'].sum()
        unpaid_flat_fees = unpaid_df['Fee Amount'].sum()
        
        total_unpaid_payout = (unpaid_hours * hourly_rate) + unpaid_flat_fees
        
        m_col1, m_col2, m_col3 = st.columns(3)
        m_col1.metric("Total Hours Logged", f"{total_hours:.2f}")
        m_col2.metric("Unpaid Flat Fees", f"${unpaid_flat_fees:,.2f}")
        m_col3.metric("Total Unpaid Payout", f"${total_unpaid_payout:,.2f}")

        # --- ALTAIR CHART ---
        st.write(f"### Hourly Breakdown by Client: {selected_period}")
        hourly_chart_df = display_df[display_df['Entry Type'] == "Hourly Work"]
        
        if not hourly_chart_df.empty:
            chart_prep = hourly_chart_df.groupby(['Client', 'Status'])['Hours'].sum().reset_index()
            
            bar_chart = alt.Chart(chart_prep).mark_bar().encode(
                x=alt.X('Client:N', axis=alt.Axis(labelAngle=0), title=None),
                y=alt.Y('Hours:Q', title='Total Hours'),
                color=alt.Color('Status:N', scale=alt.Scale(domain=['Paid', 'Unpaid'], range=['#A50000', '#555555']))
            ).properties(height=400)
            
            st.altair_chart(bar_chart, use_container_width=True)
        else:
            st.info("No hourly data to display for this period.")
        
        # --- FUNCTION: Mark as Paid ---
        st.divider()
        if len(unpaid_df) > 0:
            if st.button(f"✅ Mark all '{selected_period}' entries as Paid"):
                if selected_period == "All Time":
                    existing_data['Status'] = "Paid"
                else:
                    month_mask = pd.to_datetime(existing_data['Date']).dt.strftime('%B %Y') == selected_period
                    existing_data.loc[month_mask, 'Status'] = "Paid"
                
                conn.update(worksheet="Log", data=existing_data)
                st.success(f"Updated all entries for {selected_period} to Paid!")
                st.rerun()

        # --- UPDATED AI INVOICE SUMMARIES (LINE-ITEM FORMAT)[cite: 1] ---
        st.divider()
        st.subheader("📋 Invoice Line-Item Summaries")
        st.write("Each hourly entry will be listed by date for easy copy-pasting.")
        
        if ai_ready:
            try:
                available_models = [m.name.replace('models/', '') for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                selected_model = st.selectbox("Select API Model:", available_models)
                
                if st.button(f"✨ Generate Line Items for {selected_period}"):
                    model = genai.GenerativeModel(selected_model)
                    
                    # Only process hourly work[cite: 1]
                    if len(hourly_chart_df) == 0:
                        st.info("No hourly tasks found to summarize for this period.")
                    
                    for client_name in hourly_chart_df['Client'].unique():
                        client_entries = hourly_chart_df[hourly_chart_df['Client'] == client_name].sort_values(by='Date')
                        
                        # Prepare raw data for AI formatting[cite: 1]
                        data_to_format = ""
                        for _, row in client_entries.iterrows():
                            formatted_date = row['Date'].strftime('%m/%d/%Y')
                            data_to_format += f"Date: {formatted_date} | Hours: {row['Hours']} | Task: {row['Task']}\n"
                        
                        # Structured prompt for line-item generation[cite: 1]
                        prompt = (
                            f"You are a billing assistant. Please format the following work entries for {client_name} "
                            "into professional invoice line items. For each entry, provide exactly one line. "
                            "Format each line as: [Date] - [Hours] hours - [Description]. "
                            "The description should be a more professional version of the 'Task' provided. "
                            "Do not include headers, intros, or summaries. Just the lines.\n\n"
                            f"{data_to_format}"
                        )
                        
                        response = model.generate_content(prompt)
                        
                        with st.expander(f"**Invoice Ready: {client_name}**", expanded=True):
                            # Displaying in a code block makes it easier to copy without formatting issues[cite: 1]
                            st.code(response.text, language="text")
                            st.caption("Highlight and copy the text above directly onto your invoice.")
                            
            except Exception as e:
                st.error(f"AI Error: {e}")
    else:
        st.info("No entries logged yet.")

# ==========================================
# TAB 2: LOG NEW WORK
# ==========================================
with tab_entry:
    st.header("Log New Work")
    entry_type = st.radio("Compensation Type", ["Hourly Work", "Flat Rate Fee"], horizontal=True)
    st.divider()
    
    with st.form(key="time_entry_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            entry_date = st.date_input("Date", value=date.today())
            day_of_week = entry_date.strftime("%A")
        with col2:
            client_selection = st.selectbox("Client / Case", options=client_list if client_list else ["No Clients Found"])
        
        if entry_type == "Hourly Work":
            hours_worked = st.number_input("Hours Worked", min_value=0.0, step=0.25)
            fee_amount = 0.0
            task_description = st.text_area("Task(s) Completed", placeholder="Drafted rebuttal, reviewed case files...")
        else:
            hours_worked = 0.0
            fee_amount = st.number_input("Flat Fee Amount ($)", min_value=0.0, step=50.0)
            task_description = "Flat Rate Service"
            st.info("Task descriptions are not required for flat rate fees.")

        submit_button = st.form_submit_button(label="Save Entry")

        if submit_button:
            if (entry_type == "Hourly Work" and hours_worked > 0 and task_description.strip() != "") or (entry_type == "Flat Rate Fee" and fee_amount > 0):
                new_row = pd.DataFrame([{
                    "Date": entry_date.strftime("%Y-%m-%d"),
                    "Day": day_of_week,
                    "Hours": hours_worked,
                    "Client": client_selection,
                    "Task": task_description,
                    "Status": "Unpaid",
                    "Entry Type": entry_type,
                    "Fee Amount": fee_amount
                }])
                
                cols_to_keep = ["Date", "Day", "Hours", "Client", "Task", "Status", "Entry Type", "Fee Amount"]
                clean_existing = existing_data[[c for c in cols_to_keep if c in existing_data.columns]]
                
                updated_df = pd.concat([clean_existing, new_row], ignore_index=True)
                conn.update(worksheet="Log", data=updated_df)
                st.success(f"Successfully logged {entry_type} for {client_selection}!")
                st.rerun()
            else:
                st.warning("Please fill out all required fields.")

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