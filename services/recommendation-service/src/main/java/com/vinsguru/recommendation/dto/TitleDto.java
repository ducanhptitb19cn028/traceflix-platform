package com.vinsguru.recommendation.dto;

/** Mirror of catalog-service's TitleDto (the upstream response shape). */
public record TitleDto(Integer id,
                       String name,
                       String genre,
                       Integer releaseYear,
                       Double rating) {
}
