"""Install a synthetic export fixture in this isolated worktree, never production."""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("variant", choices=["none", "css", "motion"])
args = parser.parse_args()
source = Path(__file__).resolve().parent
root = source.parents[2]
assert (root / "Qualify/creative_pages.py").is_file()
page = root / "Qualify/creative_pages.py"
text = page.read_text().replace("from Qualify.pasos12_spike import spike_cards\n", "")
text = text.replace("            spike_cards(),\n", "")
if args.variant != "none":
    text = text.replace("import reflex as rx", "import reflex as rx\n\nfrom Qualify.pasos12_spike import spike_cards", 1)
    start = text.index("def drafts_index()")
    pos = text.index("        _padded(", start) + len("        _padded(")
    text = text[:pos] + "\n            spike_cards()," + text[pos:]
    component = (source / ("css.jsx" if args.variant == "css" else "motion.jsx")).read_text()
    component = component[:component.index("createRoot(document.getElementById")]
    component = component.replace("const motionMode=MODE==='motion';", "const motionMode=true;")
    component = component.replace("import('./features.js')", "import('./pasos12_features.js')")
    component += "\nexport { App as MotionCardList };\n"
    (root / "Qualify/pasos12_cards.jsx").write_text(component)
    (root / "Qualify/pasos12_style.css").write_text((source / "style.css").read_text())
    (root / "Qualify/pasos12_features.js").write_text((source / "features.js").read_text())
    features = '_features = rx.asset("pasos12_features.js", shared=True)\n' if args.variant == "motion" else ""
    dependency = '    lib_dependencies = ["motion@14.6.0"]\n' if args.variant == "motion" else ""
    wrapper = '''"""Synthetic export fixture. Do not merge this prototype."""
import reflex as rx
_source = rx.asset("pasos12_cards.jsx", shared=True)
_style = rx.asset("pasos12_style.css", shared=True)
FEATURES
class MotionCardList(rx.NoSSRComponent):
    library = f"$/public{_source}"
    tag = "MotionCardList"
DEPENDENCY
    def add_imports(self):
        return {"": f"$/public{_style}"}

spike_cards = MotionCardList.create
'''
    (root / "Qualify/pasos12_spike.py").write_text(wrapper.replace("FEATURES", features).replace("DEPENDENCY", dependency))
page.write_text(text)
print(f"Prepared synthetic {args.variant} fixture in isolated worktree")
