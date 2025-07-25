import streamlit as st

# Use hardcoded creds or replace with secrets (see Step 5)
USERNAME = "admin"
PASSWORD = "password123"

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

def show_login():
    st.title("Login to Home Weavers Portal")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if username == USERNAME and password == PASSWORD:
            st.session_state.logged_in = True
            st.experimental_rerun()
        else:
            st.error("Invalid username or password")

def show_main():
    st.write("Welcome! This is the main app after login.")
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.experimental_rerun()

if not st.session_state.logged_in:
    show_login()
else:
    show_main()
