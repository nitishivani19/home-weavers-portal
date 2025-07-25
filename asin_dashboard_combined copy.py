import streamlit as st
import pandas as pd
import time
import re
from io import BytesIO
from sqlalchemy import create_engine, text
from datetime import datetime

# Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

DB_PATH = "asin_checker.db"
engine = create_engine(f"sqlite:///" + DB_PATH)

BASE_PRODUCT_COLS = ["ASIN", "URL", "Collection Name", "Size", "Color", "Customer"]
RESULT_COLS = ["Final URL", "Price", "Is Redirect", "Is Unavailable", "Orderable", "Last Checked"]

st.set_page_config(page_title="ASIN Manager & Dashboard", layout="wide")

# --- Professional Styling ---
st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] button {
        font-size: 20px;
        font-weight: 700;
        padding: 8px 20px;
        margin-right: 8px;
    }
    .stApp header {visibility: hidden;}
    .stDataFrame thead tr th, .stDataEditor thead tr th {
        background: #f5f6fa;
        color: #2d3436;
        font-size: 15px;
        font-weight: 700;
    }
    .stDataFrame tbody tr td, .stDataEditor tbody tr td {
        font-size: 15px;
        padding: 10px 6px;
    }
    .stButton > button {
        font-size: 16px;
        border-radius: 6px;
        border: 1.5px solid #318a41;
        color: #318a41;
        background: #fff;
        font-weight: 500;
        margin: 0 8px 0 0;
        transition: background 0.15s;
    }
    .stButton > button:hover {
        background: #e8f5e9;
        color: #26732c;
    }
    .stTextInput>div>div>input {
        font-size: 15px;
        border-radius: 6px;
    }
    .stForm {
        background: #f9f9f9;
        padding: 20px 30px 20px 20px;
        border-radius: 10px;
        box-shadow: 0 1px 4px rgba(50,50,90,0.10);
        margin-bottom: 25px;
    }
    .stDownloadButton button {
        border-radius: 6px;
        color: #1976d2;
        border: 1.5px solid #1976d2;
        background: #f2f7fb;
        font-weight: 600;
    }
    .stDownloadButton button:hover {
        background: #e3f2fd;
    }
    .stDivider {margin: 14px 0;}
    </style>
""", unsafe_allow_html=True)

def extract_asin(url):
    match = re.search(r"/dp/([A-Z0-9]{10})|/gp/product/([A-Z0-9]{10})", url)
    if match:
        return match.group(1) or match.group(2)
    parts = url.strip("/").split("/")
    for part in reversed(parts):
        if len(part) == 10 and part.isalnum():
            return part
    return ""

def ensure_table():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS asins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                "ASIN" TEXT,
                "URL" TEXT,
                "Collection Name" TEXT,
                "Size" TEXT,
                "Color" TEXT,
                "Customer" TEXT
            )
        """))

def ensure_status_columns():
    col_defs = {col: "TEXT" for col in RESULT_COLS}
    with engine.begin() as conn:
        res = conn.execute(text("PRAGMA table_info(asins)"))
        current_cols = [row[1] for row in res.fetchall()]
        for col, coltype in col_defs.items():
            if col not in current_cols:
                try:
                    conn.execute(text(f'ALTER TABLE asins ADD COLUMN "{col}" {coltype}'))
                except Exception:
                    pass

def get_all_asins():
    ensure_table()
    ensure_status_columns()
    df = pd.read_sql('SELECT * FROM asins', con=engine)
    for col in BASE_PRODUCT_COLS + RESULT_COLS + ["id"]:
        if col not in df.columns:
            df[col] = ""
    return df

def add_asin_row(row_dict):
    ensure_table()
    ensure_status_columns()
    df_all = get_all_asins()
    if "URL" in df_all.columns and row_dict["URL"] in df_all["URL"].values:
        return False
    asin = extract_asin(row_dict["URL"])
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO asins ("ASIN", "URL", "Collection Name", "Size", "Color", "Customer")
                    VALUES (:ASIN, :URL, :Collection_Name, :Size, :Color, :Customer)
                """),
                {
                    "ASIN": asin,
                    "URL": row_dict["URL"],
                    "Collection_Name": row_dict["Collection Name"],
                    "Size": row_dict["Size"],
                    "Color": row_dict["Color"],
                    "Customer": row_dict["Customer"]
                }
            )
        return True
    except Exception as e:
        st.error(f"ERROR inserting row for URL {row_dict['URL']}: {e}")
        return False

def add_asins_bulk(df_upload):
    ensure_table()
    ensure_status_columns()
    df_all = get_all_asins()
    added, skipped = 0, 0
    for i, row in df_upload.iterrows():
        row_dict = row.to_dict()
        if "URL" in df_all.columns and row_dict["URL"] in df_all["URL"].values:
            skipped += 1
            continue
        result = add_asin_row(row_dict)
        if result:
            added += 1
        else:
            st.error(f"Could not add row in bulk for URL: {row_dict['URL']}")
    return added, skipped

def delete_asin(id):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM asins WHERE id = :id"), {"id": id})

def update_asin(id, asin, url, collection, size, color, customer):
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE asins SET
                "ASIN"=:ASIN, "URL"=:URL, "Collection Name"=:Collection,
                "Size"=:Size, "Color"=:Color, "Customer"=:Customer
                WHERE id=:id
            """),
            {
                "id": id,
                "ASIN": asin,
                "URL": url,
                "Collection": collection,
                "Size": size,
                "Color": color,
                "Customer": customer
            }
        )

def update_status_columns(row):
    row_id = row.get("id", row.get("ID"))
    if pd.isnull(row_id):
        return
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE asins SET
                    "Final URL" = :final_url,
                    "Price" = :price,
                    "Is Redirect" = :is_redirect,
                    "Is Unavailable" = :is_unavailable,
                    "Orderable" = :orderable,
                    "Last Checked" = :last_checked
                WHERE id = :id
            """),
            {
                "final_url": row.get("Final URL", None),
                "price": row.get("Price", None),
                "is_redirect": row.get("Is Redirect", None),
                "is_unavailable": row.get("Is Unavailable", None),
                "orderable": row.get("Orderable", None),
                "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "id": int(row_id)
            }
        )

def get_empty_template():
    df_template = pd.DataFrame(columns=BASE_PRODUCT_COLS)
    output = BytesIO()
    df_template.to_excel(output, index=False)
    output.seek(0)
    return output

# Scraping utilities
def extract_asin_from_url(url):
    match = re.search(r"/dp/([A-Z0-9]{10})", url)
    if match:
        return match.group(1)
    return None

def get_final_url_and_html(driver, url):
    try:
        driver.get(url)
        time.sleep(8)
        final_url = driver.current_url
        html = driver.page_source
        return final_url, html
    except TimeoutException:
        return url, ""

def extract_price_from_html(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    price_ids = [
        'price_inside_buybox', 'priceblock_ourprice',
        'priceblock_dealprice', 'priceblock_saleprice',
    ]
    for pid in price_ids:
        el = soup.find(id=pid)
        if el and el.text.strip():
            return el.text.strip().replace('\n', '').replace('$', '').strip()
    price_whole = soup.find('span', {'class': 'a-price-whole'})
    price_fraction = soup.find('span', {'class': 'a-price-fraction'})
    if price_whole:
        whole = price_whole.text.strip().replace(',', '').replace('$', '')
        fraction = price_fraction.text.strip() if price_fraction else "00"
        if whole.endswith('.'):
            whole = whole[:-1]
        price = f"{whole}.{fraction}"
        return price
    price_offscreen = soup.find('span', {'class': 'a-offscreen'})
    if price_offscreen and price_offscreen.text.strip():
        return price_offscreen.text.strip().replace('\n', '').replace('$', '').strip()
    return ""

def is_orderable_from_html(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    add_to_cart = soup.find('input', {'id': 'add-to-cart-button'})
    buy_now = soup.find('input', {'id': 'buy-now-button'})
    atc_button = soup.find('button', {'id': 'add-to-cart-button'})
    buy_now_button = soup.find('button', {'id': 'buy-now-button'})
    if add_to_cart or buy_now or atc_button or buy_now_button:
        return True
    unavailable_texts = [
        "Currently unavailable", "We don't know when or if this item will be back",
        "This product is not available", "out of stock", "unavailable",
        "Sorry, we couldn't find that page."
    ]
    for msg in unavailable_texts:
        if msg.lower() in html.lower():
            return False
    return False

def process_asin(driver, input_url):
    original_asin = extract_asin_from_url(input_url)
    final_url, html = get_final_url_and_html(driver, input_url)
    final_asin = extract_asin_from_url(final_url)
    price = extract_price_from_html(html)
    is_redirect = (original_asin != final_asin)
    orderable = is_orderable_from_html(html)
    is_unavailable = not orderable
    if is_redirect:
        orderable = False
        is_unavailable = True
    return final_url, price, is_redirect, is_unavailable, orderable

def run_status_check(df):
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    final_urls, prices, redirects, unavailables, orderables = [], [], [], [], []
    progress = st.progress(0, text="Checking ASINs...")

    for idx, url in enumerate(df["URL"]):
        final_url, price, is_redirect, is_unavailable, orderable = process_asin(driver, url)
        final_urls.append(final_url)
        prices.append(price)
        redirects.append("Yes" if is_redirect else "No")
        unavailables.append("Yes" if is_unavailable else "No")
        orderables.append("Yes" if orderable else "No")
        progress.progress((idx+1)/len(df), text=f"Checking {idx+1} of {len(df)} ASINs...")

    driver.quit()
    df["Final URL"] = final_urls
    df["Price"] = prices
    df["Is Redirect"] = redirects
    df["Is Unavailable"] = unavailables
    df["Orderable"] = orderables

    db_df = get_all_asins()
    id_col = "id" if "id" in db_df.columns else ("ID" if "ID" in db_df.columns else None)
    if not id_col:
        st.error("No 'id' column found in database.")
        return df

    if id_col not in df.columns:
        df = df.merge(db_df[["URL", id_col]], on="URL", how="left")
    if id_col not in df.columns:
        st.error("ID column not found after merging. Please make sure all your URLs are in the database before running the status check.")
        return df

    df = df[df[id_col].notnull()]
    for _, row in df.iterrows():
        update_status_columns(row)
    return df

# --- Select All utility ---
def select_all_checkbox(df, key_prefix):
    all_selected = st.checkbox("Select All Visible", value=False, key=f"{key_prefix}_select_all")
    if all_selected:
        df["Selected"] = True
    else:
        df["Selected"] = False
    return df

st.title("ASIN Product Manager & Dashboard")

tab1, tab_select, tab_result, tab3 = st.tabs([
    "Manage Products", 
    "Select ASINs to Check", 
    "Status Check Results", 
    "Summary Dashboard"
])

# --- 1. MANAGE PRODUCTS ---
with tab1:
    st.header("Manage Products")
    st.subheader("Add a Product Row Manually")
    with st.form("add_row_form", clear_on_submit=True):
        url = st.text_input("Amazon Product URL (required)")
        collection = st.text_input("Collection Name")
        size = st.text_input("Size")
        color = st.text_input("Color")
        customer = st.text_input("Customer")
        submitted = st.form_submit_button("Add Product Row")
        if submitted and url:
            success = add_asin_row({
                "URL": url.strip(),
                "Collection Name": collection.strip(),
                "Size": size.strip(),
                "Color": color.strip(),
                "Customer": customer.strip()
            })
            if success:
                st.success("Added!")
                st.rerun()
            else:
                st.error("This URL already exists in your database.")

    st.divider()
    st.download_button(
        label="Download Blank Excel Template",
        data=get_empty_template(),
        file_name="asin_upload_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    st.subheader("Bulk Upload Products from Excel")
    excel_file = st.file_uploader(
        "Upload Excel (must include 'URL'; other columns optional)",
        type=["xlsx"],
        key="bulk_upload"
    )
    if excel_file:
        df_upload = pd.read_excel(excel_file)
        if "URL" not in df_upload.columns:
            st.error("Your Excel must have a 'URL' column.")
        else:
            added, skipped = add_asins_bulk(df_upload)
            st.success(f"Added: {added} product(s). Skipped (already exist): {skipped}")

    st.divider()
    st.subheader("Current Product Database (Edit, Select, Bulk Delete)")

    df_asins = get_all_asins()
    id_col = "id" if "id" in df_asins.columns else ("ID" if "ID" in df_asins.columns else None)
    show_cols = [id_col] + BASE_PRODUCT_COLS if id_col else BASE_PRODUCT_COLS
    df_show = df_asins[show_cols].copy()

    # --- FILTERS ---
    with st.expander("Filters"):
        fcols = st.columns(6)
        filter_asin = fcols[0].text_input("ASIN", key="f_asin_manage")
        filter_collection = fcols[1].text_input("Collection Name", key="f_coll_manage")
        filter_size = fcols[2].text_input("Size", key="f_size_manage")
        filter_color = fcols[3].text_input("Color", key="f_color_manage")
        filter_customer = fcols[4].text_input("Customer", key="f_cust_manage")
        filter_url = fcols[5].text_input("URL", key="f_url_manage")
        if filter_asin:
            df_show = df_show[df_show["ASIN"].str.contains(filter_asin, case=False, na=False)]
        if filter_collection:
            df_show = df_show[df_show["Collection Name"].str.contains(filter_collection, case=False, na=False)]
        if filter_size:
            df_show = df_show[df_show["Size"].str.contains(filter_size, case=False, na=False)]
        if filter_color:
            df_show = df_show[df_show["Color"].str.contains(filter_color, case=False, na=False)]
        if filter_customer:
            df_show = df_show[df_show["Customer"].str.contains(filter_customer, case=False, na=False)]
        if filter_url:
            df_show = df_show[df_show["URL"].str.contains(filter_url, case=False, na=False)]

    # Insert selection checkbox column
    df_show.insert(0, "Selected", False)
    df_show = select_all_checkbox(df_show, "manage")

    # Display editable table
    edited = st.data_editor(
        df_show,
        key="manage_products_editor",
        column_config={"Selected": st.column_config.CheckboxColumn("Select")},
        use_container_width=True,
        num_rows="dynamic",
        hide_index=True,
        disabled=[id_col],  # Don't allow editing of the id column
    )

    # Get selected rows for actions
    selected_rows = edited[edited["Selected"]].copy()

    col1, col2 = st.columns(2)
    with col1:
        if st.button(f"Delete Selected ({len(selected_rows)})", key="bulk_delete_manage"):
            for row_id in selected_rows[id_col]:
                delete_asin(row_id)
            st.success(f"Deleted {len(selected_rows)} ASIN(s).")
            st.rerun()
    with col2:
        if st.button("Save Edits", key="save_edits_manage"):
            for _, row in edited.iterrows():
                update_asin(row[id_col], row["ASIN"], row["URL"], row["Collection Name"], row["Size"], row["Color"], row["Customer"])
            st.success("All changes saved!")
            st.rerun()

# -- 2. SELECT ASINS TO CHECK --
with tab_select:
    st.header("Select ASINs to Check Status")
    df_asins = get_all_asins()
    id_col = "id" if "id" in df_asins.columns else ("ID" if "ID" in df_asins.columns else None)
    if not id_col:
        st.error("Database missing id column.")
        st.stop()

    show_cols = [id_col] + BASE_PRODUCT_COLS + ["Last Checked"] if id_col else BASE_PRODUCT_COLS + ["Last Checked"]
    df_show = df_asins[show_cols].copy()

    # --- FILTERS ---
    with st.expander("Filters"):
        cols = st.columns(6)
        filter_asin = cols[0].text_input("ASIN", key="asin_filter_select")
        filter_collection = cols[1].text_input("Collection", key="col_filter_select")
        filter_size = cols[2].text_input("Size", key="size_filter_select")
        filter_color = cols[3].text_input("Color", key="color_filter_select")
        filter_customer = cols[4].text_input("Customer", key="customer_filter_select")
        cutoff_str = cols[5].text_input("Not checked since (YYYY-MM-DD)", value="")
        if filter_asin:
            df_show = df_show[df_show["ASIN"].str.contains(filter_asin, case=False, na=False)]
        if filter_collection:
            df_show = df_show[df_show["Collection Name"].str.contains(filter_collection, case=False, na=False)]
        if filter_size:
            df_show = df_show[df_show["Size"].str.contains(filter_size, case=False, na=False)]
        if filter_color:
            df_show = df_show[df_show["Color"].str.contains(filter_color, case=False, na=False)]
        if filter_customer:
            df_show = df_show[df_show["Customer"].str.contains(filter_customer, case=False, na=False)]
        if cutoff_str.strip():
            try:
                cutoff_dt = datetime.strptime(cutoff_str, "%Y-%m-%d")
                df_show = df_show[
                    (df_show["Last Checked"].isnull()) | 
                    (df_show["Last Checked"] == "") | 
                    (df_show["Last Checked"] < cutoff_dt.strftime("%Y-%m-%d"))
                ]
            except Exception:
                pass

    # Format columns for nice display
    if "Last Checked" in df_show.columns:
        df_show["Last Checked"] = pd.to_datetime(df_show["Last Checked"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
    if "Price" in df_show.columns:
        df_show["Price"] = df_show["Price"].apply(lambda x: f"${x}" if pd.notnull(x) and str(x).strip() != "" else "")

    # Select All
    df_show.insert(0, "Selected", False)
    df_show = select_all_checkbox(df_show, "statuscheck")

    edited = st.data_editor(
        df_show,
        key="select_asin_editor",
        column_config={"Selected": st.column_config.CheckboxColumn("Select")},
        use_container_width=True,
        num_rows="dynamic",
        hide_index=True,
        disabled=[id_col],  # Don't allow editing of the id column
    )

    selected_rows = edited[edited["Selected"]].copy()
    if st.button(f"Run Status Check for Selected ({len(selected_rows)})"):
        if len(selected_rows) == 0:
            st.warning("Select at least one ASIN to check status.")
        else:
            with st.spinner("Running status checks. Please wait..."):
                run_status_check(selected_rows)
                st.success("Status check complete! Data updated.")
                st.rerun()

# -- 3. STATUS CHECK RESULTS --
with tab_result:
    st.header("Status Check Results")
    df_asins = get_all_asins()
    df_display = df_asins.copy()

    # --- FILTERS ---
    with st.expander("Filters"):
        fcols = st.columns(8)
        filter_asin = fcols[0].text_input("ASIN", key="f_asin_results")
        filter_collection = fcols[1].text_input("Collection Name", key="f_coll_results")
        filter_size = fcols[2].text_input("Size", key="f_size_results")
        filter_color = fcols[3].text_input("Color", key="f_color_results")
        filter_customer = fcols[4].text_input("Customer", key="f_cust_results")
        filter_price = fcols[5].text_input("Price", key="f_price_results")
        filter_redirect = fcols[6].text_input("Is Redirect", key="f_redirect_results")
        filter_unavail = fcols[7].text_input("Is Unavailable", key="f_unavail_results")
        if filter_asin:
            df_display = df_display[df_display["ASIN"].str.contains(filter_asin, case=False, na=False)]
        if filter_collection:
            df_display = df_display[df_display["Collection Name"].str.contains(filter_collection, case=False, na=False)]
        if filter_size:
            df_display = df_display[df_display["Size"].str.contains(filter_size, case=False, na=False)]
        if filter_color:
            df_display = df_display[df_display["Color"].str.contains(filter_color, case=False, na=False)]
        if filter_customer:
            df_display = df_display[df_display["Customer"].str.contains(filter_customer, case=False, na=False)]
        if filter_price:
            df_display = df_display[df_display["Price"].astype(str).str.contains(filter_price, case=False, na=False)]
        if filter_redirect:
            df_display = df_display[df_display["Is Redirect"].str.contains(filter_redirect, case=False, na=False)]
        if filter_unavail:
            df_display = df_display[df_display["Is Unavailable"].str.contains(filter_unavail, case=False, na=False)]

    # Format columns for professional look
    if "Last Checked" in df_display.columns:
        df_display["Last Checked"] = pd.to_datetime(df_display["Last Checked"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
    if "Price" in df_display.columns:
        df_display["Price"] = df_display["Price"].apply(lambda x: f"${x}" if pd.notnull(x) and str(x).strip() != "" else "")

    st.dataframe(df_display[BASE_PRODUCT_COLS + RESULT_COLS], use_container_width=True, hide_index=True)
    output = BytesIO()
    df_display[BASE_PRODUCT_COLS + RESULT_COLS].to_excel(output, index=False)
    output.seek(0)
    st.download_button(
        label="Download Results as Excel",
        data=output,
        file_name="asin_status_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# -- 4. SUMMARY DASHBOARD --
with tab3:
    st.header("Summary Dashboard")
    df_asins = get_all_asins()
    df_data = df_asins
    if not df_data.empty:
        if "Orderable" not in df_data.columns:
            st.warning("No status data yet. Please run 'Run Status Check' in the Select tab first.")
        else:
            customers = sorted(df_data["Customer"].dropna().unique())
            customer_filter = st.selectbox("Select Customer", ["All"] + customers)
            if customer_filter != "All":
                df_summary = df_data[df_data["Customer"] == customer_filter]
            else:
                df_summary = df_data

            summary = (
                df_summary
                .groupby(["Collection Name", "Customer"])
                .agg(
                    Total_SKU=('URL', 'count'),
                    Orderable=('Orderable', lambda x: (x == "Yes").sum()),
                    Non_Orderable=('Orderable', lambda x: (x == "No").sum())
                )
                .reset_index()
            )
            summary["Onsite %"] = (summary["Orderable"] / summary["Total_SKU"] * 100).round(1)
            st.subheader("Summary by Collection and Customer")
            st.dataframe(summary, use_container_width=True, hide_index=True)
    else:
        st.info("No product data in database yet.")
