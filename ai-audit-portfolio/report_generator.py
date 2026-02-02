from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
import pandas as pd

styles = getSampleStyleSheet()
doc = SimpleDocTemplate("audit_report.pdf")

df = pd.read_excel("audit_flags.xlsx")
text = "Audit Risk Summary:<br/>" + "<br/>".join(df["Account"].astype(str))

doc.build([Paragraph(text, styles["BodyText"])])
print("AI audit report generated")
