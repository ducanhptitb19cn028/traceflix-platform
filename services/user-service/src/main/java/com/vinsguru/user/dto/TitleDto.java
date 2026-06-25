package com.vinsguru.user.dto;

/** Mirror of the recommendation/catalog title shape (downstream response). */
public record TitleDto(Integer id,
                       String name,
                       String genre,
                       Integer releaseYear,
                       Double rating) {
}
