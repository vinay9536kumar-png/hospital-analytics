from datetime import date, timedelta

import plotly.express as px
import streamlit as st

import ai_chat
import auth
import billing
import db

st.set_page_config(page_title="Hospital Analytics", page_icon="🏥", layout="wide")
db.ensure_columns()
user = auth.require_login()
auth.render_sidebar(user)

st.title("🏥 Hospital Analytics")
allowed_tabs = auth.ROLE_TABS[user["role"]]
tabs = dict(zip(allowed_tabs, st.tabs(allowed_tabs)))

# ---------------------------------------------------------------- Dashboard
if "Dashboard" in tabs:
    with tabs["Dashboard"]:
        today = date.today().isoformat()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Patients today", db.scalar(
            "SELECT COUNT(*) FROM visits WHERE admit_date = ?", (today,)))
        c2.metric("Currently admitted", db.scalar(
            "SELECT COUNT(*) FROM visits WHERE status = 'Admitted'"))
        c3.metric("Discharged today", db.scalar(
            "SELECT COUNT(*) FROM visits WHERE discharge_date = ? "
            "AND status IN ('Discharged', 'Referred')", (today,)))
        c4.metric("Total patients", db.scalar("SELECT COUNT(*) FROM patients"))

        days = st.slider("Days to show", 7, 90, 30)
        start = (date.today() - timedelta(days=days)).isoformat()

        daily = db.query_df(
            "SELECT admit_date AS day, COUNT(*) AS patients FROM visits "
            "WHERE admit_date >= ? GROUP BY admit_date ORDER BY admit_date", (start,))
        st.plotly_chart(px.line(daily, x="day", y="patients", title="Patients per day"),
                        width="stretch")

        left, right = st.columns(2)
        top = db.query_df(
            "SELECT disease, COUNT(*) AS patients FROM visits WHERE admit_date >= ? "
            "GROUP BY disease ORDER BY patients DESC LIMIT 10", (start,))
        left.plotly_chart(
            px.bar(top, x="patients", y="disease", orientation="h", title="Top diseases"),
            width="stretch")

        dept = db.query_df(
            "SELECT department, COUNT(*) AS patients FROM visits WHERE admit_date >= ? "
            "GROUP BY department", (start,))
        right.plotly_chart(
            px.pie(dept, names="department", values="patients", title="Patients by department"),
            width="stretch")

# -------------------------------------------------------------- Add Patient
if "Add Patient" in tabs:
    with tabs["Add Patient"]:
        mode = st.radio("Patient type", ["New patient", "Existing patient"], horizontal=True)
        patient_id = None

        if mode == "Existing patient":
            term = st.text_input("Search by name or phone")
            if term:
                found = db.search_patients(term)
                st.dataframe(found, width="stretch")
                if not found.empty:
                    patient_id = st.selectbox("Select patient ID", found["patient_id"].tolist())
                else:
                    st.warning("No patient found.")

        with st.form("visit_form", clear_on_submit=True):
            if mode == "New patient":
                st.markdown("**Patient details**")
                a, b, c = st.columns(3)
                name = a.text_input("Full name")
                age = b.number_input("Age", 0, 120, 30)
                gender = c.selectbox("Gender", ["Male", "Female", "Other"])
                d, e, f = st.columns(3)
                phone = d.text_input("Phone")
                blood_group = e.selectbox("Blood group", db.BLOOD_GROUPS)
                city = f.text_input("City")

            st.markdown("**Visit details**")
            g, h = st.columns(2)
            visit_type = g.selectbox("Visit type", ["OPD", "IPD", "Emergency"])
            disease = h.selectbox("Disease", list(db.DISEASES) + ["Other"])
            other_disease = st.text_input("If disease is Other, type it here")
            department = st.selectbox("Department", db.DEPARTMENTS)
            doctor = st.text_input("Doctor")
            admit_date = st.date_input("Visit / admit date", value=date.today())
            notes = st.text_area("Notes")
            submitted = st.form_submit_button("Save")

        if submitted:
            final_disease = other_disease.strip() if disease == "Other" else disease
            if department == "Auto":
                final_department = db.DISEASES.get(final_disease, "General Medicine")
            else:
                final_department = department

            if mode == "New patient" and not name.strip():
                st.error("Please enter the patient name.")
            elif mode == "Existing patient" and patient_id is None:
                st.error("Please search and select an existing patient first.")
            elif not final_disease:
                st.error("Please enter the disease.")
            else:
                if mode == "New patient":
                    patient_id = db.add_patient(
                        name.strip(), int(age), gender, city.strip(),
                        phone.strip(), blood_group)
                visit_id = db.add_visit(
                    patient_id, visit_type, final_disease, final_department,
                    admit_date.isoformat(), doctor.strip(), notes.strip())
                st.success(f"Saved. Patient ID: {patient_id}, Visit ID: {visit_id}")
                auth.log_action(user["username"], "add_visit",
                                f"patient {patient_id}, visit {visit_id}")

# ------------------------------------------------------------------- Search
if "Search" in tabs:
    with tabs["Search"]:
        term = st.text_input("Search by patient name, phone or patient ID", key="search_term")

        f1, f2, f3, f4 = st.columns(4)
        s_disease = f1.selectbox("Disease", ["All"] + db.distinct_values("disease"))
        s_dept = f2.selectbox("Department", ["All"] + db.distinct_values("department"))
        s_status = f3.selectbox("Status", ["All"] + db.distinct_values("status"))
        s_type = f4.selectbox("Visit type", ["All"] + db.distinct_values("visit_type"))

        d1, d2 = st.columns(2)
        use_dates = d1.checkbox("Filter by date range")
        start_date = end_date = None
        if use_dates:
            start_date = d1.date_input("From", value=date.today() - timedelta(days=30), key="s_from")
            end_date = d2.date_input("To", value=date.today(), key="s_to")

        can_see_bills = user["role"] in auth.BILL_VIEW_ROLES
        pay_filter = "All"
        if can_see_bills:
            pay_filter = d2.selectbox(
                "Payment status",
                ["All", "Unpaid", "Partially paid", "Paid", "No charges"],
                key="s_pay",
            )

        results = db.search_visits(
            term.strip(), s_disease, s_dept, s_status, s_type,
            start_date.isoformat() if start_date else None,
            end_date.isoformat() if end_date else None,
            include_billing=can_see_bills,
        )
        if can_see_bills and pay_filter != "All":
            results = results[results["payment_status"] == pay_filter]
        st.caption(f"{len(results)} record(s) found (showing at most 500)")
        if can_see_bills and not results.empty:
            b1, b2, b3 = st.columns(3)
            b1.metric("Total billed", f"Rs. {results['bill_total'].sum():,.2f}")
            b2.metric("Collected", f"Rs. {results['bill_paid'].sum():,.2f}")
            b3.metric("Outstanding", f"Rs. {results['bill_balance'].sum():,.2f}")
        st.dataframe(results, width="stretch", hide_index=True)

        if not results.empty:
            st.download_button(
                "Download results as CSV",
                results.to_csv(index=False).encode("utf-8"),
                file_name="search_results.csv",
                mime="text/csv",
            )
            st.markdown("**Patient history**")
            hist_id = st.selectbox(
                "Select a patient ID to see all their visits",
                results["patient_id"].drop_duplicates().tolist(),
            )
            st.dataframe(db.patient_history(hist_id), width="stretch", hide_index=True)

# ------------------------------------------------------------------- Ask AI
if "Ask AI" in tabs:
    with tabs["Ask AI"]:
        st.markdown(
            "Ask about patient numbers in Hindi or English. Example: "
            "*How many patients came today?*, *Which disease was most common this week?*, "
            "*Kal kitne patients discharge hue?*"
        )
        st.caption(
            "Privacy: only your question and the table structure go to the AI. "
            "Patient records never leave this computer, and the chat is read-only."
        )

        examples = [
            "How many patients came today?",
            "Top 5 diseases in the last 30 days",
            "How many patients are currently admitted?",
            "Department wise patients this month",
        ]
        cols = st.columns(len(examples))
        for col, example in zip(cols, examples):
            if col.button(example, key=f"ex_{example}"):
                st.session_state["ai_question"] = example

        question = st.text_input("Your question", key="ai_question")

        if st.button("Ask", key="ai_ask") and question.strip():
            try:
                with st.spinner("Thinking..."):
                    sql, result = ai_chat.ask(question.strip())
                    auth.log_action(user["username"], "ask_ai", question.strip()[:200])
                if result.empty:
                    st.info("No matching records found.")
                elif result.shape == (1, 1):
                    st.metric(result.columns[0], result.iloc[0, 0].item()
                              if hasattr(result.iloc[0, 0], "item") else result.iloc[0, 0])
                else:
                    st.dataframe(result, width="stretch", hide_index=True)
                with st.expander("Show the SQL that was used"):
                    st.code(sql, language="sql")
            except ai_chat.UnsafeQuery as exc:
                st.warning(str(exc))
            except Exception as exc:
                st.error(f"Could not answer that question: {exc}")

# ------------------------------------------------------------------ Billing
if "Billing" in tabs:
    with tabs["Billing"]:
        with st.expander("Hospital details printed on the bill"):
            hospital_name = st.text_input("Hospital name", "City Care Hospital", key="h_name")
            hospital_address = st.text_input("Address", "", key="h_addr")
            hospital_phone = st.text_input("Phone", "", key="h_phone")

        bill_term = st.text_input("Find patient (name, phone or patient ID)", key="bill_term")
        visits = db.search_visits(bill_term.strip(), limit=50)

        if visits.empty:
            st.info("No visits found.")
        else:
            labels = {
                int(r.visit_id): f"Visit {r.visit_id} | {r.name} | {r.disease} | {r.admit_date} | {r.status}"
                for r in visits.itertuples()
            }
            visit_id = st.selectbox(
                "Select visit", list(labels), format_func=lambda v: labels[v], key="bill_visit")
            header = db.get_visit_header(visit_id)
            st.markdown(
                f"**{header['name']}** (ID {header['patient_id']}), {header['age']} / {header['gender']}  \n"
                f"{header['visit_type']} - {header['department']} - {header['disease']} - "
                f"admitted {header['admit_date']}"
            )

            with st.form("bill_item_form", clear_on_submit=True):
                a, b, c, d = st.columns([2, 4, 1, 2])
                category = a.selectbox("Category", db.BILL_CATEGORIES)
                description = b.text_input("Description")
                quantity = c.number_input("Qty", min_value=0.0, value=1.0, step=1.0)
                unit_price = d.number_input("Rate (Rs.)", min_value=0.0, value=0.0, step=50.0)
                if st.form_submit_button("Add charge"):
                    if not description.strip():
                        st.error("Please enter a description.")
                    elif quantity <= 0 or unit_price <= 0:
                        st.error("Quantity and rate must be more than zero.")
                    else:
                        db.add_bill_item(visit_id, category, description.strip(),
                                         quantity, unit_price)
                        st.rerun()

            items = db.get_bill_items(visit_id)
            if items.empty:
                st.info("No charges added yet for this visit.")
            else:
                st.dataframe(items, width="stretch", hide_index=True)
                r1, r2 = st.columns([3, 1])
                remove_id = r1.selectbox("Remove a charge (item ID)", items["item_id"].tolist())
                if r2.button("Remove"):
                    db.delete_bill_item(int(remove_id))
                    st.rerun()

            meta = db.get_bill_meta(visit_id)
            with st.form("bill_payment_form"):
                e, f, g = st.columns(3)
                discount = e.number_input("Discount (Rs.)", min_value=0.0,
                                          value=meta["discount"], step=50.0)
                paid_amount = f.number_input("Amount paid (Rs.)", min_value=0.0,
                                             value=meta["paid_amount"], step=100.0)
                payment_mode = g.selectbox(
                    "Payment mode", db.PAYMENT_MODES,
                    index=db.PAYMENT_MODES.index(meta["payment_mode"])
                    if meta["payment_mode"] in db.PAYMENT_MODES else 0)
                if st.form_submit_button("Save payment details"):
                    db.save_bill_meta(visit_id, discount, paid_amount, payment_mode)
                    st.rerun()

            summary = db.bill_summary(visit_id)
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Subtotal", f"Rs. {summary['subtotal']:,.2f}")
            m2.metric("Discount", f"Rs. {summary['discount']:,.2f}")
            m3.metric("Total", f"Rs. {summary['total']:,.2f}")
            m4.metric("Paid", f"Rs. {summary['paid']:,.2f}")
            m5.metric("Balance due", f"Rs. {summary['balance']:,.2f}")
            st.caption(f"Payment status: {summary['status']}")

            if not items.empty:
                pdf_bytes = billing.make_bill_pdf(
                    visit_id, hospital_name, hospital_address, hospital_phone)
                st.download_button(
                    "Download bill (PDF)", pdf_bytes,
                    file_name=f"bill_{visit_id}_{header['name'].replace(' ', '_')}.pdf",
                    mime="application/pdf",
                    on_click=auth.log_action,
                    args=(user["username"], "download_bill", f"visit {visit_id}"),
                )

# ---------------------------------------------------------------- Discharge
if "Discharge" in tabs:
    with tabs["Discharge"]:
        admitted = db.get_admitted()
        if admitted.empty:
            st.info("No admitted patients right now.")
        else:
            st.dataframe(admitted, width="stretch")
            visit_id = st.selectbox("Visit ID to discharge", admitted["visit_id"].tolist())
            outcome = st.radio("Outcome", ["Discharged", "Referred"], horizontal=True)
            if st.button("Confirm discharge"):
                db.discharge_visit(visit_id, outcome, date.today().isoformat())
                auth.log_action(user["username"], "discharge", f"visit {visit_id}: {outcome}")
                st.success(f"Visit {visit_id} marked as {outcome}. Reopen this tab to refresh the list.")


# -------------------------------------------------------------------- Users
if "Users" in tabs:
    with tabs["Users"]:
        auth.render_user_admin(user)