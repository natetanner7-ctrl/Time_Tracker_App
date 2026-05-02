import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import date

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

# --- Header & Logo ---
col1, col2 = st.columns([1, 5]) # Creates a small column for the logo, large one for text

with col1:
    # Make sure "logo.png" matches the exact name of your saved image file
    st.image("logo.png", width=200) 

with col2:
    st.title("Time Tracking & Payroll")

# --- 2. Establish Google Sheets Connection ---
conn = st.connection("gsheets", type=GSheetsConnection)

try:
    # Reading 5 columns: Date, Day, Hours, Client, Task
    existing_data = conn.read(worksheet="Log", usecols=[0, 1, 2, 3, 4], ttl=0)
    existing_data = existing_data.dropna(how="all") 
except Exception as e:
    st.error("Could not connect to the Google Sheet. Double-check your secrets.toml file.")
    st.stop()

# --- 3. Create the Tab System ---
tab_dashboard, tab_entry = st.tabs([" Payroll Dashboard (Boss View)", " Log New Hours"])

# ==========================================
# TAB 1: THE BOSS'S DASHBOARD
# ==========================================
with tab_dashboard:
    if not existing_data.empty and len(existing_data) > 0:
        
        # BUG FIX: We make a copy of the data just for the dashboard. 
        # This prevents the calculated 'Month' column from accidentally being saved to the Google Sheet!
        dashboard_data = existing_data.copy()
        
        # Date parsing
        dashboard_data['Date'] = pd.to_datetime(dashboard_data['Date'], format='mixed')
        dashboard_data['Month'] = dashboard_data['Date'].dt.strftime('%B %Y')
        
        # --- Filters & Dynamic Pay Rate ---
        st.subheader("Payroll Filter")
        col_rate, col_period = st.columns(2)
        
        with col_rate:
            hourly_rate = st.number_input("💵 Set Hourly Rate ($)", min_value=0.0, value=35.00, step=1.00, format="%.2f")
            
        with col_period:
            months_available = ["All Time"] + dashboard_data['Month'].unique().tolist()
            selected_period = st.selectbox("📅 Select Pay Period", months_available)
            
        st.divider()
        
        # --- Filter the Data based on selection ---
        if selected_period == "All Time":
            display_df = dashboard_data.copy()
            chart_grouping = 'Month'
        else:
            display_df = dashboard_data[dashboard_data['Month'] == selected_period].copy()
            chart_grouping = 'Date' 
            
        # --- Calculate Payout ---
        total_hours = display_df['Hours'].sum()
        total_pay = total_hours * hourly_rate
        
        # Display large, clean metrics for the boss
        m_col1, m_col2 = st.columns(2)
        m_col1.metric(label="Total Hours", value=f"{total_hours:.2f} hrs")
        m_col2.metric(label="Total Payout Owed", value=f"${total_pay:,.2f}")
        
        # --- Render Chart ---
        if selected_period == "All Time":
            chart_data = display_df.groupby('Month')['Hours'].sum().reset_index()
            chart_data['Date_Sort'] = pd.to_datetime(chart_data['Month'])
            chart_data = chart_data.sort_values('Date_Sort').set_index('Month')
        else:
            chart_data = display_df.groupby('Date')['Hours'].sum().reset_index()
            chart_data['Date'] = chart_data['Date'].dt.strftime('%Y-%m-%d')
            chart_data = chart_data.set_index('Date')
            
        st.bar_chart(chart_data['Hours'], color="#A50000")
        
        # --- CSV Export Button ---
        # Exporting all 5 relevant columns now
        export_cols = [col for col in ['Date', 'Day', 'Hours', 'Client', 'Task'] if col in display_df.columns]
        export_df = display_df[export_cols].copy()
        export_df['Date'] = export_df['Date'].dt.strftime('%Y-%m-%d')
        csv_data = export_df.to_csv(index=False).encode('utf-8')
        
        st.download_button(
            label=f"📥 Download {selected_period} Report for Payroll",
            data=csv_data,
            file_name=f"Time_Report_{selected_period.replace(' ', '_')}.csv",
            mime="text/csv"
        )
        
    else:
        st.info("No hours logged yet! Go to the 'Log New Hours' tab to get started.")

# ==========================================
# TAB 2: YOUR TIME ENTRY WORKSPACE
# ==========================================
with tab_entry:
    st.header("Log New Hours")

    # A temporary list of clients to test the dropdown
    client_list = ["Client A - Smith Case", "Client B - Doe Case", "Internal / Admin"]

    with st.form(key="time_entry_form", clear_on_submit=True):
        col1, col2, col3 = st.columns([1, 1, 1.5])
        
        with col1:
            entry_date = st.date_input("Date", value=date.today())
            day_of_week = entry_date.strftime("%A")
            st.text_input("Day", value=day_of_week, disabled=True) 
            
        with col2:
            hours_worked = st.number_input("Hours Worked", min_value=0.0, step=0.25, format="%.2f")
            
        with col3:
            # Client Dropdown
            client_selection = st.selectbox("Client / Case", options=client_list)
            
        # Text area for detailed task entry
        task_description = st.text_area("Task(s) Completed", placeholder="E.g., Drafted rebuttal, reviewed case files, client call...")
        
        submit_button = st.form_submit_button(label="Log Hours")

        if submit_button:
            if hours_worked > 0 and task_description.strip() != "":
                
                # Ensuring we only write the 5 correct columns to the sheet
                new_row = pd.DataFrame([{
                    "Date": entry_date.strftime("%Y-%m-%d"),
                    "Day": day_of_week,
                    "Hours": hours_worked,
                    "Client": client_selection,
                    "Task": task_description
                }])
                
                # If existing data has columns we don't want (like an old Month column), we filter them out before saving
                cols_to_keep = ["Date", "Day", "Hours", "Client", "Task"]
                clean_existing_data = existing_data[[c for c in cols_to_keep if c in existing_data.columns]]
                
                updated_df = pd.concat([clean_existing_data, new_row], ignore_index=True)
                conn.update(worksheet="Log", data=updated_df)
                
                st.success(f"Successfully logged {hours_worked} hours for {client_selection}! Refreshing dashboard...")
                st.rerun()
            elif hours_worked <= 0:
                st.warning("Please enter a valid number of hours (greater than 0).")
            else:
                st.warning("Please enter a brief description of the tasks completed.")