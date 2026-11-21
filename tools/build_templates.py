"""Build data/letter_templates.npz from screenshots of letter-tile rows.

    python tools/build_templates.py row1.png GABCDEFGHIJKLMNOP row2.png QRSTUVWXYZ

Each image is a screenshot of a row of tiles; the string after it lists the
letters in left-to-right order. Only the templates are stored, not the images.
"""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from finish_the_word.tiles import find_tiles  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "letter_templates.npz"


def main(argv):
    if len(argv) < 2 or len(argv) % 2:
        print(__doc__)
        return 2
    letters, masks = [], []
    for img_path, text in zip(argv[0::2], argv[1::2]):
        img = cv2.imread(img_path)
        tiles = find_tiles(img)
        if len(tiles) != len(text):
            print(f"{img_path}: found {len(tiles)} tiles but {len(text)} letters given")
            return 1
        for t, ch in zip(tiles, text):
            if t.mask is None:
                print(f"{img_path}: no letter found in tile for {ch!r}")
                return 1
            letters.append(ch.lower())
            masks.append(t.mask)
    np.savez_compressed(OUT, letters=np.array(letters), masks=np.stack(masks))
    print(f"wrote {len(letters)} templates to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
