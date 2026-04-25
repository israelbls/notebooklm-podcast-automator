"""Source management operations for NotebookLM Automator."""

import logging
from typing import Any, Callable, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

logger = logging.getLogger(__name__)


def group_sources(sources: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Group URL and YouTube sources together into a single item with newlines."""
    url_like_types = {"url", "youtube"}
    url_like_sources = [
        source for source in sources if source.get("type") in url_like_types
    ]
    other_sources = [
        source for source in sources if source.get("type") not in url_like_types
    ]

    new_sources = []
    if url_like_sources:
        joined_content = "\n".join(
            source.get("content", "") for source in url_like_sources
        )
        join_type = url_like_sources[0].get("type", "url")
        new_sources.append({"type": join_type, "content": joined_content})
    new_sources.extend(other_sources)
    return new_sources


class SourceManager:
    """Manages source operations for a NotebookLM page."""

    def __init__(self, page: "Page", get_text: Callable[[str], str]):
        self.page = page
        self._get_text = get_text

    def is_dialog_open(self) -> bool:
        """Check if the add source dialog is open."""
        try:
            dialog = self.page.locator("mat-dialog-container").last
            return dialog.is_visible()
        except Exception:
            return False

    def open_dialog(self) -> None:
        """Open the add source dialog."""
        if self.is_dialog_open():
            return

        add_button = self.page.locator(
            f"button:has-text('{self._get_text('add_source_button')}')"
        ).first
        if add_button.count() == 0 or not add_button.is_visible():
            raise RuntimeError("Could not locate the 'Add source' button")

        add_button.click()
        self.page.wait_for_timeout(500)

    def close_dialog(self) -> None:
        """Close the add source dialog if open."""
        if not self.is_dialog_open():
            return

        close_button = self.page.locator(
            "button:has(mat-icon:has-text('close'))"
        ).first
        if close_button.count() > 0 and close_button.is_visible():
            close_button.click()
            self.page.wait_for_timeout(200)
            return

        close_icon = self.page.locator("mat-icon", has_text="close").first
        if close_icon.count() > 0 and close_icon.is_visible():
            close_icon.click()
            self.page.wait_for_timeout(200)

    def add_url(self, source_type: str, url: str) -> None:
        """Add a URL or YouTube source."""
        self.open_dialog()
        try:
            type_text = self._get_text(
                "source_type_youtube" if source_type == "youtube" else "source_type_website"
            )
            if type_text:
                chip = self.page.locator(
                    "mat-chip-option, .mdc-evolution-chip, span.mat-mdc-chip-action",
                    has_text=type_text
                ).first
                if chip.count() > 0 and chip.is_visible():
                    chip.click()
                else:
                    chip = self.page.get_by_text(type_text, exact=True).first
                    if chip.count() > 0 and chip.is_visible():
                        chip.click()

            inp = self.page.locator("textarea[formcontrolname='newUrl']").first
            if inp.count() == 0 or not inp.is_visible():
                inp = self.page.locator(
                    "input[type='url'], input[placeholder*='http'], textarea[placeholder*='Search the web for new sources']"
                ).first

            if inp.count() == 0 or not inp.is_visible():
                placeholder = self._get_text("url_input_placeholder")
                if placeholder:
                    inp = self.page.get_by_placeholder(placeholder, exact=False).first

            if inp.count() == 0 or not inp.is_visible():
                raise RuntimeError(f"Could not find URL input field for {source_type}")

            inp.fill(url)
            self.page.wait_for_timeout(500)

            insert_text = self._get_text("insert_button")
            insert_btn = self.page.get_by_role("button", name=insert_text).first

            if insert_btn.count() > 0 and insert_btn.is_visible():
                insert_btn.click()
            else:
                inp.press("Enter")

            self.page.wait_for_timeout(100)
        finally:
            self.close_dialog()

    def add_text(self, text_content: str) -> None:
        """Add a text source via the 'Copied text' option."""
        self.open_dialog()
        try:
            type_text = self._get_text("source_type_text")
            chip = None
            if type_text:
                chip = self.page.locator(
                    "mat-chip-option, .mdc-evolution-chip, span.mat-mdc-chip-action",
                    has_text=type_text
                ).first
                if chip.count() == 0 or not chip.is_visible():
                    chip = self.page.get_by_text(type_text, exact=True).first
            if chip and chip.count() > 0 and chip.is_visible():
                chip.click()

            dialog = self.page.locator("mat-dialog-container").last
            if not dialog or dialog.count() == 0 or not dialog.is_visible():
                dialog = self.page

            textarea = dialog.locator(
                "textarea[formcontrolname='textInput'], "
                "textarea[formcontrolname='newText'], "
                "textarea"
            ).first

            if textarea.count() == 0 or not textarea.is_visible():
                raise RuntimeError(
                    "Could not find text input field for copied text source"
                )

            textarea.fill(text_content)
            self.page.wait_for_timeout(500)

            insert_text = self._get_text("insert_button")
            insert_btn = self.page.get_by_role("button", name=insert_text).first

            if insert_btn.count() > 0 and insert_btn.is_visible():
                insert_btn.click()
            else:
                textarea.press("Enter")

            self.page.wait_for_timeout(100)
        finally:
            self.close_dialog()

    def add_sources(self, sources: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Add multiple sources to the notebook."""
        self.close_dialog()
        results = []

        grouped_sources = group_sources(sources)
        for source in grouped_sources:
            source_type = source.get("type")
            content = source.get("content")
            result = {"source": source, "success": False, "error": None}

            try:
                if source_type in ["url", "youtube"]:
                    self.add_url(source_type, content)
                elif source_type == "text":
                    self.add_text(content)
                else:
                    raise ValueError(f"Unknown source type: {source_type}")

                result["success"] = True
            except Exception as e:
                logger.error(f"Error adding source {content}: {e}")
                result["error"] = str(e)

            results.append(result)
            self.page.wait_for_timeout(100)

        return results

    def clear_sources(self) -> Dict[str, Any]:
        """Clear all sources from the notebook."""
        removed = 0

        def get_source_items():
            return self.page.locator("div.single-source-container")

        max_attempts = 200
        for _ in range(max_attempts):
            source_items = get_source_items()
            if source_items.count() == 0:
                break

            source = source_items.first
            try:
                more_button = source.locator("button.source-item-more-button").first
                if more_button.count() == 0 or not more_button.is_visible():
                    more_button = source.locator(
                        "button:has(mat-icon:has-text('more_vert'))"
                    ).first

                if more_button.count() == 0 or not more_button.is_visible():
                    logger.warning("Could not locate 'more' button for a source item.")
                    break

                more_button.click()
                self.page.wait_for_timeout(200)

                delete_text = self._get_text("delete_source_menu_item")
                menu_item = self.page.get_by_role("menuitem", name=delete_text).first
                if menu_item.count() > 0 and menu_item.is_visible():
                    menu_item.click()
                else:
                    logger.warning("Could not find 'Remove source' menu item.")
                    break
                self.page.wait_for_timeout(200)

                confirm_text = self._get_text("confirm_delete_button")
                confirm_button = self.page.get_by_role(
                    "button", name=confirm_text
                ).first
                if confirm_button.count() > 0 and confirm_button.is_visible():
                    confirm_button.click()
                else:
                    logger.warning(
                        "Could not find confirmation button when removing a source."
                    )
                    break

                try:
                    source.wait_for(state="detached", timeout=1000)
                except Exception:
                    logger.warning(
                        "Source item did not disappear after delete confirmation."
                    )

                removed += 1
                self.page.wait_for_timeout(500)
            except Exception as e:
                logger.error(f"Failed to remove a source: {e}")
                break

        return {"success": removed > 0, "count": removed}

