package com.vinsguru.catalog.service;

import com.vinsguru.catalog.dto.TitleDto;
import com.vinsguru.catalog.entity.Title;
import com.vinsguru.catalog.repository.TitleRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CatalogServiceTest {

    @Mock
    private TitleRepository repository;

    @InjectMocks
    private CatalogService service;

    private static Title title(int id, String name, String genre, double rating) {
        var t = new Title();
        t.setId(id);
        t.setName(name);
        t.setGenre(genre);
        t.setReleaseYear(2000);
        t.setRating(rating);
        return t;
    }

    @Test
    void listAll_mapsEntitiesToDtos() {
        when(repository.findAll()).thenReturn(List.of(
                title(1, "Inception", "Sci-Fi", 8.8),
                title(2, "The Matrix", "Sci-Fi", 8.7)));

        List<TitleDto> result = service.listAll();

        assertThat(result).hasSize(2);
        assertThat(result.getFirst().name()).isEqualTo("Inception");
        assertThat(result.getFirst().rating()).isEqualTo(8.8);
    }

    @Test
    void getTitle_returnsDtoWhenPresent() {
        when(repository.findById(1)).thenReturn(Optional.of(title(1, "Inception", "Sci-Fi", 8.8)));

        Optional<TitleDto> result = service.getTitle(1);

        assertThat(result).isPresent();
        assertThat(result.get().genre()).isEqualTo("Sci-Fi");
    }

    @Test
    void getTitle_emptyWhenMissing() {
        when(repository.findById(99)).thenReturn(Optional.empty());

        assertThat(service.getTitle(99)).isEmpty();
    }

    @Test
    void search_delegatesToRepositoryAndMaps() {
        when(repository.findByNameContainingIgnoreCaseOrGenreContainingIgnoreCase("sci", "sci"))
                .thenReturn(List.of(title(1, "Inception", "Sci-Fi", 8.8)));

        List<TitleDto> result = service.search("sci");

        assertThat(result).singleElement()
                          .extracting(TitleDto::name).isEqualTo("Inception");
    }

    @Test
    void search_nullQueryTreatedAsEmpty() {
        when(repository.findByNameContainingIgnoreCaseOrGenreContainingIgnoreCase("", ""))
                .thenReturn(List.of());

        assertThat(service.search(null)).isEmpty();
    }

}
