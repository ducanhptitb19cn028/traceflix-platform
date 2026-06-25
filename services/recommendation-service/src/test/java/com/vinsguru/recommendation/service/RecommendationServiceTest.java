package com.vinsguru.recommendation.service;

import com.vinsguru.recommendation.client.CatalogClient;
import com.vinsguru.recommendation.dto.TitleDto;
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
class RecommendationServiceTest {

    @Mock
    private CatalogClient catalogClient;

    @InjectMocks
    private RecommendationService service;

    private static TitleDto title(int id, double rating) {
        return new TitleDto(id, "Title " + id, "Drama", 2000, rating);
    }

    private static List<TitleDto> sevenTitles() {
        return List.of(title(1, 9.3), title(2, 9.2), title(3, 9.0),
                title(4, 8.9), title(5, 8.8), title(6, 8.7), title(7, 8.5));
    }

    @Test
    void recommend_returnsAtMostTopFive() {
        when(catalogClient.getAllTitles()).thenReturn(sevenTitles());

        List<TitleDto> result = service.recommend(1);

        assertThat(result).hasSize(5);
        verify(catalogClient).getAllTitles();
    }

    @Test
    void recommend_topResultIsAmongHighestRated() {
        when(catalogClient.getAllTitles()).thenReturn(sevenTitles());

        List<TitleDto> result = service.recommend(2);

        // the 9.3 / 9.2 titles should always surface near the top
        assertThat(result).extracting(TitleDto::rating).contains(9.3);
    }

    @Test
    void recommend_differentUsersCanGetDifferentOrdering() {
        when(catalogClient.getAllTitles()).thenReturn(sevenTitles());

        var forUser1 = service.recommend(1).stream().map(TitleDto::id).toList();
        var forUser2 = service.recommend(2).stream().map(TitleDto::id).toList();

        // both valid top-5 lists; the per-user bias makes the orderings not identical
        assertThat(forUser1).hasSize(5);
        assertThat(forUser2).hasSize(5);
        assertThat(forUser1).isNotEqualTo(forUser2);
    }

    @Test
    void recommend_handlesFewerThanTopN() {
        when(catalogClient.getAllTitles()).thenReturn(List.of(title(1, 9.0), title(2, 8.0)));

        assertThat(service.recommend(1)).hasSize(2);
    }

}
