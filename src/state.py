from dataclasses import dataclass, field
import json


@dataclass
class InstallState:
    oobe: bool = False
    pages: list = field(default_factory=list)

    def set_page(self, page_id: str, data: dict):
        """Upsert a page's data by id."""
        for i, entry in enumerate(self.pages):
            if entry.get("id") == page_id:
                self.pages[i] = {"id": page_id, **data}
                return
        self.pages.append({"id": page_id, **data})

    def get_page(self, page_id: str) -> dict | None:
        for entry in self.pages:
            if entry.get("id") == page_id:
                return entry
        return None

    def to_dict(self) -> dict:
        return {
            "oobe": self.oobe,
            "pages": self.pages,
        }

    def to_json(self, **kwargs) -> str:
        return json.dumps(self.to_dict(), **kwargs)
