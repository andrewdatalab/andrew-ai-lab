import pandas as pd
from sklearn.ensemble import IsolationForest

df = pd.read_excel("sample_gl.xlsx")

model = IsolationForest(contamination=0.02)
df["anomaly"] = model.fit_predict(df[["Amount"]])

df[df["anomaly"] == -1].to_excel("audit_flags.xlsx", index=False)
print("Audit anomaly report generated")
