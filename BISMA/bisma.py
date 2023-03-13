# 17 values needed for above ISF SGOP 2022 categories - https://en.wikipedia.org/wiki/Standard_of_Good_Practice_for_Information_Security
# Value_1 = Company name
# Value_2 = The Ambition you have as a company
# Value_3 = The Market standard aka similar companies in your market area
# Values range from 1 (non existent controls) -> 5 (fully demonstratable in control)

import plotly.graph_objects as go
import plotly.offline as pyo
from datetime import datetime

# Get current date-time.
now = datetime.now()

# Determine which quarter of the year is now. Returns Q1, Q2, Q3 or Q4.
quarter_of_the_year = f'Q{(now.month-1)//3+1}'
current_year = now.year


# ISF SGOP 2022 main categories
categories = ['Security Governance', 'Information Risk Assessment', 'Security Management', 'People Management', 'Information Management', 'Physical Asset Management', 'System Development', 'Business Application Management', 'System Access', 'System Management', 'Networks and Communications', 'Supply Chain Management', 'Technical Security Management', 'Threat and Incident Management', 'Physical and Environmental Management', 'Business Continuity', 'Security Assurance']
categories = [*categories, categories[0]]

# Company value per above categorie
Value_1 = [4, 4, 5, 4, 3, 2, 3, 5, 4, 3, 2, 1, 2, 2, 3, 4, 5]
# Same but with ambition for your company
Value_2 = [5, 5, 4, 5, 4, 5, 5, 4, 5, 4, 5, 4, 5, 4, 4, 4, 4]
# Same but now with the market standard
Value_3 = [3, 4, 5, 3, 5, 3, 2, 3, 3, 3, 4, 3, 4, 2, 3, 2, 3]
#
Value_1 = [*Value_1, Value_1[0]]
Value_2 = [*Value_2, Value_2[0]]
Value_3 = [*Value_3, Value_3[0]]


fig = go.Figure(
    data=[
        go.Scatterpolar(r=Value_1, theta=categories, name='Bol.com'),
        go.Scatterpolar(r=Value_2, theta=categories, name='Ambition'),
        go.Scatterpolar(r=Value_3, theta=categories, name='Market standard')
    ],
    layout=go.Layout(
        title=go.layout.Title(text="BISMA - Bol.com Information Security Maturity Application<br>generated at" + " " + str(current_year) + " " + str(quarter_of_the_year)),
        polar={'radialaxis': {'visible': True}},
        showlegend=True
    )
 )


fig.add_annotation(text='Security framework used:  <a href="https://en.wikipedia.org/wiki/Standard_of_Good_Practice_for_Information_Security" target="_blank">ISF SOGP 2022</a><br><br>Scoring values:<br><br>1=Not existent<br>2=Some controls in place but not enough<br>3=Controls in place but not easy to demonstrate<br>4=Partially demonstratable in control<br>5=Fully demonstratable in control',
                    align='left',
                    showarrow=False,
                    xref='paper',
                    yref='paper',
                    x=1.1,
                    y=0.8,
                    bordercolor='red',
                    borderwidth=1)

#)

pyo.plot(fig)


