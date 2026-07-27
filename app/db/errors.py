from sqlalchemy.exc import IntegrityError


def get_constraint_name(error: IntegrityError) -> str | None:
    pending: list[BaseException] = [error]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        identity = id(current)
        if identity in visited:
            continue
        visited.add(identity)

        constraint_name = getattr(current, "constraint_name", None)
        if isinstance(constraint_name, str):
            return constraint_name

        for linked_error in (
            getattr(current, "orig", None),
            current.__cause__,
            current.__context__,
        ):
            if isinstance(linked_error, BaseException):
                pending.append(linked_error)
    return None
