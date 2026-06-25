package com.vinsguru.gateway.config;

import com.vinsguru.gateway.client.MovieClient;
import com.vinsguru.gateway.client.SearchClient;
import com.vinsguru.gateway.client.UserClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;

@Configuration
public class ApplicationConfiguration {

    @Bean
    public MovieClient movieClient(RestClient.Builder builder,
                                   @Value("${movie-service.url}") String baseUrl) {
        return new MovieClient(builder.baseUrl(baseUrl).build());
    }

    @Bean
    public UserClient userClient(RestClient.Builder builder,
                                 @Value("${user-service.url}") String baseUrl) {
        return new UserClient(builder.baseUrl(baseUrl).build());
    }

    @Bean
    public SearchClient searchClient(RestClient.Builder builder,
                                     @Value("${search-service.url}") String baseUrl) {
        return new SearchClient(builder.baseUrl(baseUrl).build());
    }

}
