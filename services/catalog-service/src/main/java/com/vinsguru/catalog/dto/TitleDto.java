package com.vinsguru.catalog.dto;

public record TitleDto(Integer id,
                       String name,
                       String genre,
                       Integer releaseYear,
                       Double rating) {
}
