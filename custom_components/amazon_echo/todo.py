"""To-do lists: one entity per Alexa list."""

from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from amazon_echo import ListItem

from . import AmazonEchoConfigEntry
from .const import DOMAIN
from .coordinator import AmazonEchoCoordinator
from .entity import AmazonEchoEntity, async_add_dynamic

PARALLEL_UPDATES = 0

BUILT_IN = {"shopping": "shopping_list", "todo": "todo_list"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonEchoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one to-do entity per list."""
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda data: data.lists,
        lambda list_id: AmazonEchoTodoList(entry.runtime_data, list_id),
    )


class AmazonEchoTodoList(AmazonEchoEntity, TodoListEntity):
    """An Alexa shopping, to-do or custom list."""

    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(self, coordinator: AmazonEchoCoordinator, list_id: str) -> None:
        """Initialise the entity of one list."""
        super().__init__(coordinator, EntityDescription(key=f"list_{list_id}"))
        self._list_id = list_id
        echo_list = coordinator.data.lists[list_id][0]
        # The built-in lists have no name of their own: translate by kind.
        self._attr_translation_key = BUILT_IN.get(echo_list.kind, "list")
        self._attr_translation_placeholders = {"name": echo_list.name}

    @property
    def available(self) -> bool:
        """Unavailable once the list is deleted."""
        return super().available and self._list_id in self.data.lists

    @property
    def _items(self) -> list[ListItem]:
        return self.data.lists.get(self._list_id, (None, []))[1]

    @property
    def todo_items(self) -> list[TodoItem]:
        """Items of the list."""
        return [
            TodoItem(
                uid=item.id,
                summary=item.name,
                status=TodoItemStatus.COMPLETED
                if item.completed
                else TodoItemStatus.NEEDS_ACTION,
            )
            for item in self._items
        ]

    def _item(self, uid: str | None) -> ListItem:
        for item in self._items:
            if item.id == uid:
                return item
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="item_not_found",
            translation_placeholders={"item": str(uid)},
        )

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add an item."""
        await self.coordinator.async_write(
            self.coordinator.client.add_list_item(self._list_id, item.summary or ""),
            refresh="lists",
        )

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Rename and/or (un)complete an item."""
        await self.coordinator.async_write(
            self.coordinator.client.update_list_item(
                self._list_id,
                self._item(item.uid),
                name=item.summary,
                completed=item.status == TodoItemStatus.COMPLETED,
            ),
            refresh="lists",
        )

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete items."""
        client = self.coordinator.client
        for index, item in enumerate([self._item(uid) for uid in uids], 1):
            await self.coordinator.async_write(
                client.delete_list_item(self._list_id, item),
                refresh="lists" if index == len(uids) else None,
            )
