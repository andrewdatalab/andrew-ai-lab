import pandas as pd

df = pd.read_excel("sample_gl.xlsx")
summary = df.groupby("Account")["Amount"].sum()

summary.to_excel("monthly_summary.xlsx")
print("Monthly financial summary created")
