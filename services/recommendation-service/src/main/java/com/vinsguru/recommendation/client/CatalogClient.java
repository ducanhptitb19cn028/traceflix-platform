package com.vinsguru.recommendation.client;

import com.vinsguru.recommendation.dto.TitleDto;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.web.client.RestClient;

import java.util.List;

public class CatalogClient {

    private final RestClient restClient;

    public CatalogClient(RestClient restClient) {
        this.restClient = restClient;
    }

    public List<TitleDto> getAllTitles() {
        return this.restClient.get()
                              .uri("/api/catalog")
                              .retrieve()
                              .body(new ParameterizedTypeReference<List<TitleDto>>() {
                              });
    }

}
