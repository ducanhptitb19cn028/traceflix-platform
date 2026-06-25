package com.vinsguru.recommendation.config;

import com.vinsguru.recommendation.client.CatalogClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;

@Configuration
public class ApplicationConfiguration {

    @Bean
    public CatalogClient catalogClient(RestClient.Builder builder,
                                       @Value("${catalog-service.url}") String baseUrl) {
        return new CatalogClient(builder.baseUrl(baseUrl).build());
    }

}
