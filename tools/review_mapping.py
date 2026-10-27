#!/usr/bin/env python3
"""One-time research helper. Archive project-owned manifests for catalog mapping review.

This is not part of the registry auditor's network surface. It only reads the
explicit URLs below and never executes any fetched content.
"""

import concurrent.futures
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "algokit-subscriber-ts": (
        "@algorandfoundation/algokit-subscriber",
        "https://raw.githubusercontent.com/algorandfoundation/algokit-subscriber-ts/main/package.json",
    ),
    "algokit-client-generator-ts": (
        "@algorandfoundation/algokit-client-generator",
        "https://raw.githubusercontent.com/algorandfoundation/algokit-client-generator-ts/main/package.json",
    ),
    "algokit-utils-ts": (
        "@algorandfoundation/algokit-utils",
        "https://raw.githubusercontent.com/algorandfoundation/algokit-utils-ts/main/package.json",
    ),
    "ens-js": (
        "@ensdomains/ensjs",
        "https://raw.githubusercontent.com/ensdomains/ensjs/main/packages/ensjs/package.json",
    ),
    "folks-algorand-sdk": (
        "@folks-finance/algorand-sdk",
        "https://raw.githubusercontent.com/Folks-Finance/algorand-js-sdk/main/package.json",
    ),
    "iso-filecoin-react": (
        "iso-filecoin-react",
        "https://raw.githubusercontent.com/hugomrdias/filecoin/main/packages/iso-filecoin-react/package.json",
    ),
    "iso-filecoin-wallets": (
        "iso-filecoin-wallets",
        "https://raw.githubusercontent.com/hugomrdias/filecoin/main/packages/iso-filecoin-wallets/package.json",
    ),
    "metamask-eth-sig-util": (
        "@metamask/eth-sig-util",
        "https://raw.githubusercontent.com/MetaMask/eth-sig-util/main/package.json",
    ),
    "pera-connect": (
        "@perawallet/connect",
        "https://raw.githubusercontent.com/perawallet/connect/main/package.json",
    ),
    "safe-api-kit": (
        "@safe-global/api-kit",
        "https://raw.githubusercontent.com/safe-global/safe-core-sdk/main/packages/api-kit/package.json",
    ),
    "safe-protocol-kit": (
        "@safe-global/protocol-kit",
        "https://raw.githubusercontent.com/safe-global/safe-core-sdk/main/packages/protocol-kit/package.json",
    ),
    "safe-relay-kit": (
        "@safe-global/relay-kit",
        "https://raw.githubusercontent.com/safe-global/safe-core-sdk/main/packages/relay-kit/package.json",
    ),
    "solc-js": ("solc", "https://raw.githubusercontent.com/argotorg/solc-js/master/package.json"),
    "somnia-contracts-sdk": (
        "@somnia-chain/contracts-sdk",
        "https://raw.githubusercontent.com/somnia-chain/contract-registry/main/sdk/package.json",
    ),
    "somnia-data-streams-sdk": (
        "@somnia-chain/streams",
        "https://raw.githubusercontent.com/somnia-chain/somnia-data-streams-sdk/main/package.json",
    ),
    "synapse-core": (
        "@filoz/synapse-core",
        "https://raw.githubusercontent.com/FilOzone/synapse-sdk/master/packages/synapse-core/package.json",
    ),
    "synapse-react": (
        "@filoz/synapse-react",
        "https://raw.githubusercontent.com/FilOzone/synapse-sdk/master/packages/synapse-react/package.json",
    ),
    "synapse-sdk": (
        "@filoz/synapse-sdk",
        "https://raw.githubusercontent.com/FilOzone/synapse-sdk/master/packages/synapse-sdk/package.json",
    ),
    "viem": ("viem", "https://raw.githubusercontent.com/wevm/viem/main/src/package.json"),
}


def main():
    target = ROOT / "sources" / "mapping-review"
    target.mkdir(parents=True, exist_ok=True)

    def inspect(pair):
        slug, (package, url) = pair
        result = {
            "catalog_slug": slug,
            "expected_package": package,
            "source_url": url,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "scope": "Mapping identity only. Development manifests are not used as release dependency evidence.",
        }
        try:
            with urlopen(
                Request(url, headers={"User-Agent": "EvidenceLedger-source-review"}), timeout=20
            ) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                result["http_status"] = response.status
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("manifest too large")
            result["sha256"] = hashlib.sha256(raw).hexdigest()
            body = target / (slug + ".json")
            body.write_bytes(raw)
            data = json.loads(raw)
            result["declared_package"] = data.get("name")
            result["identity_matches"] = data.get("name") == package
            result["body_path"] = body.name
        except HTTPError as exc:
            result["http_status"] = exc.code
            result["error"] = str(exc)
        except (OSError, ValueError) as exc:
            result["error"] = str(exc)
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(inspect, SOURCES.items()))
    (target / "review.json").write_text(json.dumps(results, indent=2) + "\n")
    for r in results:
        print(
            r["catalog_slug"],
            r.get("identity_matches"),
            r.get("declared_package"),
            r.get("error", ""),
        )


if __name__ == "__main__":
    main()
