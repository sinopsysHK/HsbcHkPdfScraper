from hsbcpdfscraper import accountstatement

st = accountstatement.Statement(".\\working\\mypdffile.pdf")
st.process()

json = st.get_json()
df = st.get_df()

print(json)