package com.vinsguru.search.client;

import com.vinsguru.search.dto.TitleDto;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.web.client.RestClient;

import java.util.List;

public class CatalogClient {

    private final RestClient restClient;

    public CatalogClient(RestClient restClient) {
        this.restClient = restClient;
    }

    public List<TitleDto> search(String query) {
        return this.restClient.get()
                              .uri(b -> b.path("/api/catalog/search")
                                         .queryParam("q", query)
                                         .build())
                              .retrieve()
                              .body(new ParameterizedTypeReference<List<TitleDto>>() {
                              });
    }

}
