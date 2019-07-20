from HsbcAccStatementHKScraper import Statement

st = Statement(".\\working\\mypdffile.pdf")
st.process()

json = st.get_json()
df = st.get_df()

print(json)