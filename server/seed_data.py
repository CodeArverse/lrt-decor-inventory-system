"""Starting data for a brand-new server database (copied from the original dashboard.py)."""

ID_PREFIXES = {
    "Structural & Track Systems": "STR",
    "Mechanisms & Hardware": "MEC",
    "Fasteners & Fixings": "FAS",
    "Sealants, Insulation & Finishing": "SEA",
    "Tools & Consumables": "TOL",
}

# Each entry is a name, or (name, unit) when the unit isn't the group's default.
SEED_ITEMS = [
    ("Structural & Track Systems", "Panels", "pcs", ["Panel"]),
    ("Structural & Track Systems", "Track Components", "pcs", [
        "Alum Trail Track H.D (Heavy Duty)", "Alum Rail Track Staking", "Aluminum Reel Track",
    ]),
    ("Structural & Track Systems", "Wall Guides & Angles", "pcs", [
        "Angle Bar 1x1x15 3/4", "Angle Bar 2x2x3 M.", "Angle Bar 1 Hole/H.D", "Angle Bar 2 Hole/ H.D",
        "Angle Bar 2 Hole", "Angle Bar 1 Hole", "Angle Bar 1/2x3", "C-Channel",
        "Support Flat Bar/ Traded", "Flat bar - 100pcs", "Flat bar LCP with knot",
        ("G.I Flat Sheet", "sheet"),
    ]),
    ("Mechanisms & Hardware", "Mechanisms", "pcs", ["Jack Mechanism", "Lcp Mechanism", "Telescopic"]),
    ("Mechanisms & Hardware", "Handles & Operating Gear", "pcs", ["Operating Handle", "Socket Hand Impact"]),
    ("Mechanisms & Hardware", "Rollers", "pcs", [
        "Glidder Deluxe Roller", "Glidder Heavyduy Roller", "4 Wheels Roller", "3 Wheels Roller",
    ]),
    ("Mechanisms & Hardware", "Locking & Sealing Components", "pcs", [
        "Lock Door", "Folding Door", "DropSeal", "Bolt Carrier", "Rubber DropSeal",
    ]),
    ("Fasteners & Fixings", "Bolts", "pcs", [
        "G.I Bolt 5/16x2", "G.I Bolt 1/4x3", "G.I Bolt 5/16x3", "G.I Bolt 1/4x1", "G.I Bolt 5/16 Uno", "Bolt 1/4 x3",
    ]),
    ("Fasteners & Fixings", "Screws (Metal & Wood)", "pcs", [
        "Metal Screw 8 3/4", "Metal Screw 6 1/2", "Black Screw 1 1/2", "Black Screw 1",
        "Wood Screw 10x1 1/2", "Flat Head Metal Screw 8x2", "Flat Head Metal Screw 1 1/2",
        "Self Drilling 10x100", "Logscrew 5/16x2", "Metal Tox 5/16x2",
    ]),
    ("Fasteners & Fixings", "Rivets & Pins", "pcs", [
        "Cutter Pin 1/8", "B.I Rivet 3/16", "Blint Rivet 3/16", "Blint Rivet 3/16 x 1/2", "Blint Rivet 1/8x1/2",
    ]),
    ("Fasteners & Fixings", "Washers & Nuts", "pcs", [
        "Nut 1/2", "Nut 3/8", "Nut 1/4", "Lock Washer 1/2", "Lock Washer 3/8",
        "Lock Washer 5/16", "Lock Washer 1/4", "Lock Washer", "Flat Washer 3/16",
    ]),
    ("Fasteners & Fixings", "Anchors (Plastic)", "pcs", ["Plastic Tox 6mm", "Plastic Tox 8mm", "Plastic w/rod"]),
    ("Fasteners & Fixings", "Knots / Nuts (G.I)", "pcs", ["G.I Knot 5/16", "G.I Knot 1/4"]),
    ("Sealants, Insulation & Finishing", "Insulation", "pcs", [
        "Wool Insulation 0.6M x 1.2M 50mm Thickness 60kg", "InsulationFoam",
    ]),
    ("Sealants, Insulation & Finishing", "Seals & Gaskets", "pcs", [
        "Rubber BulbSeal 10ft", "Rubber BulbSeal 9ft", "Rubber BulbSeal 8ft",
        "Rubber BulNose Male", "Rubber BulNose Female", "Strap Strip/strap",
    ]),
    ("Sealants, Insulation & Finishing", "Boards & Sheets", "sheet", ["Particle Board"]),
    ("Tools & Consumables", "General", "pcs", [
        ("Welding Rod 1KL", "kg"), ("Stretch Film", "roll"), "SUPER DIKIT Rugby",
    ]),
]
