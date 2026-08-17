"""Page-number pagination for API collection endpoints.

Default page size 50, maximum 100 (the client may request up to 100 with the
``page_size`` query parameter; larger values are clamped).
"""

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class ApiPageNumberPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response(
            {
                "count": self.page.paginator.count,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "results": data,
            }
        )
