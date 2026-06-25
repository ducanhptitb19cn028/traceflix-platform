package com.vinsguru.search.service;

import com.vinsguru.search.client.CatalogClient;
import com.vinsguru.search.dto.TitleDto;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class SearchServiceTest {

    @Mock
    private CatalogClient catalogClient;

    @InjectMocks
    private SearchService service;

    private static TitleDto title(int id, double rating) {
        return new TitleDto(id, "Title " + id, "Drama", 2000, rating);
    }

    @Test
    void search_ranksHitsByRatingDescending() {
        when(catalogClient.search("matrix")).thenReturn(List.of(
                title(1, 8.5), title(2, 9.1), title(3, 8.8)));

        List<TitleDto> result = service.search("matrix");

        assertThat(result).extracting(TitleDto::rating)
                          .containsExactly(9.1, 8.8, 8.5);
        verify(catalogClient).search("matrix");
    }

    @Test
    void search_emptyResultsPassThrough() {
        when(catalogClient.search("zzz")).thenReturn(List.of());

        assertThat(service.search("zzz")).isEmpty();
    }

}
