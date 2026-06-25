package com.vinsguru.search.service;

import com.vinsguru.search.client.CatalogClient;
import com.vinsguru.search.dto.TitleDto;
import org.springframework.stereotype.Service;

import java.util.Comparator;
import java.util.List;

@Service
public class SearchService {

    private final CatalogClient catalogClient;

    public SearchService(CatalogClient catalogClient) {
        this.catalogClient = catalogClient;
    }

    /** Delegate matching to the catalog, then rank hits by rating (best first). */
    public List<TitleDto> search(String query) {
        return this.catalogClient.search(query)
                                 .stream()
                                 .sorted(Comparator
                                         .comparingDouble((TitleDto t) ->
                                                 t.rating() == null ? 0.0 : t.rating())
                                         .reversed())
                                 .toList();
    }

}
