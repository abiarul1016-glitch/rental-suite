# this is just a test file, to test the json structure

import json

with open("houses.json") as file:
    data = json.load(file)

for property in data["properties"]:
    subsections = property["subsections"]

    for subsection in subsections:
        if subsection["active"]:
            print(subsection["id"])

# print(data["properties"][0]["subsections"])
