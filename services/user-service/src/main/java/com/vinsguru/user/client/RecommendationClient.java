package com.vinsguru.user.client;

import com.vinsguru.user.dto.TitleDto;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.web.client.RestClient;

import java.util.List;

public class RecommendationClient {

    private final RestClient restClient;

    public RecommendationClient(RestClient restClient) {
        this.restClient = restClient;
    }

    public List<TitleDto> getRecommendations(Integer userId) {
        return this.restClient.get()
                              .uri(b -> b.queryParam("userId", userId).build())
                              .retrieve()
                              .body(new ParameterizedTypeReference<List<TitleDto>>() {
                              });
    }

}
