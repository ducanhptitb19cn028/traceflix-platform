package com.vinsguru.user.config;

import com.vinsguru.user.client.AuthClient;
import com.vinsguru.user.client.RecommendationClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;

@Configuration
public class ApplicationConfiguration {

    @Bean
    public AuthClient authClient(RestClient.Builder builder,
                                 @Value("${auth-service.url}") String baseUrl) {
        return new AuthClient(builder.baseUrl(baseUrl).build());
    }

    @Bean
    public RecommendationClient recommendationClient(RestClient.Builder builder,
                                                     @Value("${recommendation-service.url}") String baseUrl) {
        return new RecommendationClient(builder.baseUrl(baseUrl).build());
    }

}
