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
    existing_data = conn.read(worksheet="Log", usecols=[0, 1, 2], ttl=0)
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
        # Date parsing (Includes the 'mixed' format fix for manual entries!)
        existing_data['Date'] = pd.to_datetime(existing_data['Date'], format='mixed')
        existing_data['Month'] = existing_data['Date'].dt.strftime('%B %Y')
        
        # --- Filters & Dynamic Pay Rate ---
        st.subheader("Payroll Filter")
        col_rate, col_period = st.columns(2)
        
        with col_rate:
            # DYNAMIC PAY RATE: Boss can adjust this, it defaults to $35.00
            hourly_rate = st.number_input("💵 Set Hourly Rate ($)", min_value=0.0, value=35.00, step=1.00, format="%.2f")
            
        with col_period:
            # Creates a dropdown of all available months, plus an "All Time" option
            months_available = ["All Time"] + existing_data['Month'].unique().tolist()
            selected_period = st.selectbox("📅 Select Pay Period", months_available)
            
        st.divider()
        
        # --- Filter the Data based on selection ---
        if selected_period == "All Time":
            display_df = existing_data.copy()
            chart_grouping = 'Month'
        else:
            # Filter down to just the selected month
            display_df = existing_data[existing_data['Month'] == selected_period].copy()
            chart_grouping = 'Date' # If a specific month is selected, show a daily bar chart
            
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
        export_df = display_df[['Date', 'Day', 'Hours']].copy()
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

    with st.form(key="time_entry_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            entry_date = st.date_input("Date", value=date.today())
            day_of_week = entry_date.strftime("%A")
            st.text_input("Day", value=day_of_week, disabled=True) 
            
        with col2:
            hours_worked = st.number_input("Hours Worked", min_value=0.0, step=0.25, format="%.2f")
        
        submit_button = st.form_submit_button(label="Log Hours")

        if submit_button:
            if hours_worked > 0:
                new_row = pd.DataFrame([{
                    "Date": entry_date.strftime("%Y-%m-%d"),
                    "Day": day_of_week,
                    "Hours": hours_worked
                }])
                
                updated_df = pd.concat([existing_data, new_row], ignore_index=True)
                conn.update(worksheet="Log", data=updated_df)
                
                st.success("Hours successfully logged! Refreshing dashboard...")
                st.rerun()
            else:
                st.warning("Please enter a valid number of hours (greater than 0).")