"""Keep the native userspace verification in step with the reviewed Nova identity."""
def prepare(helpers, plan):
    if plan.get('sukisu_family') != 'nova':
        return
    path = helpers / f"verify-sukisu-{plan['sukisu_code']}-userspace.py"
    text = path.read_text(encoding='utf-8')
    old, new = "b'com.sukisu.ultra'", "b'com.sukisu.nova'"
    if text.count(old) != 1:
        raise ValueError('Native userspace manager identity anchor changed')
    old_formula = f"40000 + {plan['sukisu_count']} - 2815"
    new_formula = f"30000 + {plan['sukisu_count']} + 996"
    if text.count(old_formula) != 1:
        raise ValueError('Native userspace version receipt anchor changed')
    path.write_text(text.replace(old, new).replace(old_formula, new_formula),
                    encoding='utf-8', newline='\n')
